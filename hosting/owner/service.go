package main

import (
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-webauthn/webauthn/protocol"
	"github.com/go-webauthn/webauthn/webauthn"
)

const host = "owner.bhakti.eeshan.xyz"
const origin = "https://" + host
const sessionCookie = "__Host-bhakti-session"
const ceremonyCookie = "__Host-bhakti-ceremony"

// Directory is deployment-owned and outside every document root. Now and the
// failure hook are supplied only by in-process tests, never HTTP/CGI input.
type Service struct {
	Directory   string
	Now         func() time.Time
	afterRename func() error
}

func (s *Service) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}
func jsonResponse(w http.ResponseWriter, status int, value any) {
	data, e := json.Marshal(value)
	if e != nil {
		status = 503
		data = []byte(`{"error":"The private inbox is temporarily unavailable."}`)
	}
	data = append(data, '\n')
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(status)
	w.Write(data)
}
func errorResponse(w http.ResponseWriter, e error) {
	var api *apiError
	if errors.As(e, &api) {
		jsonResponse(w, api.status, map[string]string{"error": api.message})
		return
	}
	jsonResponse(w, 503, map[string]string{"error": "The private inbox is temporarily unavailable. Please retry."})
}
func cookieValue(r *http.Request, name string) string {
	value := ""
	count := 0
	for _, c := range r.Cookies() {
		if c.Name == name {
			value = c.Value
			count++
		}
	}
	if count != 1 || !validToken(value) {
		return ""
	}
	return value
}
func setCookie(w http.ResponseWriter, name, value string, ttl time.Duration) {
	http.SetCookie(w, &http.Cookie{Name: name, Value: value, Path: "/", Secure: true, HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: int(ttl.Seconds())})
}
func decodeBody(r *http.Request, out any) error {
	content, _, e := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if e != nil || content != "application/json" {
		return errInvalid
	}
	raw, e := io.ReadAll(io.LimitReader(r.Body, (512<<10)+1))
	if e != nil || len(raw) > 512<<10 || !utf8.Valid(raw) {
		return errInvalid
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if e = decoder.Decode(out); e != nil {
		return errInvalid
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return errInvalid
	}
	return nil
}
func trustedRequest(r *http.Request) bool {
	if r.Host != host || r.TLS == nil {
		return false
	}
	for key := range r.Header {
		lower := strings.ToLower(key)
		if lower == "forwarded" || strings.HasPrefix(lower, "x-forwarded-") {
			return false
		}
	}
	return r.Method != "POST" || r.Header.Get("Origin") == origin
}
func (s *Service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Apache must finish its bounded CGI request pipe even when access is denied.
	if r.Body != nil && r.ContentLength > 0 && r.ContentLength <= 512<<10 {
		defer io.Copy(io.Discard, io.LimitReader(r.Body, 512<<10))
	}
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Frame-Options", "DENY")
	w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
	if !trustedRequest(r) {
		errorResponse(w, errDenied)
		return
	}
	if r.Method != "GET" && r.Method != "POST" {
		w.Header().Set("Allow", "GET, POST")
		jsonResponse(w, 405, map[string]string{"error": "Method not allowed."})
		return
	}
	if r.Method == "GET" && !strings.HasPrefix(r.URL.Path, "/api/") {
		serveWeb(w, r)
		return
	}
	var e error
	switch r.URL.Path {
	case "/api/auth/begin", "/api/setup/begin", "/api/auth/finish", "/api/setup/finish":
		if r.Method != "POST" {
			e = errInvalid
		} else {
			e = s.authentication(w, r)
		}
	case "/api/session", "/api/logout", "/api/requests", "/api/export":
		e = s.inbox(w, r)
	default:
		jsonResponse(w, 404, map[string]string{"error": "Not found."})
		return
	}
	if e != nil {
		errorResponse(w, e)
	}
}
func newWebAuthn() (*webauthn.WebAuthn, error) {
	return webauthn.New(&webauthn.Config{RPID: host, RPDisplayName: "Bhakti", RPOrigins: []string{origin}, RPTopOriginVerificationMode: protocol.TopOriginExplicitVerificationMode, AuthenticatorSelection: protocol.AuthenticatorSelection{UserVerification: protocol.VerificationRequired, ResidentKey: protocol.ResidentKeyRequirementRequired}, Timeouts: webauthn.TimeoutsConfig{Login: webauthn.TimeoutConfig{Timeout: challengeLifetime}, Registration: webauthn.TimeoutConfig{Timeout: challengeLifetime}}})
}
func bootstrapAllowed(st *state, code string, now time.Time) bool {
	return len(st.Owner.Credentials) == 0 && validToken(code) && equal(digest(code), st.BootstrapHash) && now.Before(st.BootstrapExpires)
}
func (s *Service) authentication(w http.ResponseWriter, r *http.Request) error {
	var input struct {
		Code        string          `json:"code"`
		ChallengeID string          `json:"challengeId"`
		Credential  json.RawMessage `json:"credential"`
	}
	if e := decodeBody(r, &input); e != nil {
		return e
	}
	kind := "auth"
	if strings.HasPrefix(r.URL.Path, "/api/setup/") {
		kind = "setup"
	}
	begin := strings.HasSuffix(r.URL.Path, "/begin")
	now := s.now()
	wa, e := newWebAuthn()
	if e != nil {
		return e
	}
	var response any
	var newBinding, newSession string
	e = transact(s.Directory, now, s.afterRename, func(st *state, commit func() error) error {
		if begin {
			if kind == "setup" {
				if !bootstrapAllowed(st, input.Code, now) {
					return errDenied
				}
			} else if len(st.Owner.Credentials) != 1 {
				return errDenied
			}
			if len(st.Challenges) >= maxChallenges || len(st.Begins) >= 60 {
				return errCapacity
			}
			binding := cookieValue(r, ceremonyCookie)
			if binding == "" {
				var e error
				binding, e = randomToken()
				if e != nil {
					return e
				}
				newBinding = binding
			}
			newBinding = binding // Refresh this browser ceremony window on every begin.
			id, e := randomToken()
			if e != nil {
				return e
			}
			var options any
			var data *webauthn.SessionData
			if kind == "setup" {
				created, d, err := wa.BeginRegistration(st.Owner)
				if err != nil {
					return err
				}
				options = created.Response
				data = d
			} else {
				assertion, d, err := wa.BeginLogin(st.Owner, webauthn.WithUserVerification(protocol.VerificationRequired))
				if err != nil {
					return err
				}
				options = assertion.Response
				data = d
			}
			st.Challenges[digest(id)] = challenge{kind, digest(binding), now.Add(challengeLifetime), *data}
			st.Begins = append(st.Begins, now)
			response = map[string]any{"publicKey": options, "challengeId": id}
			return commit()
		}
		if !validToken(input.ChallengeID) {
			return errDenied
		}
		ch, ok := st.Challenges[digest(input.ChallengeID)]
		if !ok {
			return errDenied
		}
		delete(st.Challenges, digest(input.ChallengeID))
		if e := commit(); e != nil {
			return e
		}
		if ch.Kind != kind || !equal(ch.Binding, digest(cookieValue(r, ceremonyCookie))) || !now.Before(ch.Expires) {
			return errDenied
		}
		if len(st.Sessions) >= maxSessions {
			return errCapacity
		}
		var credential *webauthn.Credential
		if kind == "setup" {
			if !bootstrapAllowed(st, input.Code, now) {
				return errDenied
			}
			parsed, err := protocol.ParseCredentialCreationResponseBytes(input.Credential)
			if err != nil {
				return errDenied
			}
			credential, err = wa.CreateCredential(st.Owner, ch.Session, parsed)
			if err != nil {
				return errDenied
			}
			st.Owner.Credentials = []webauthn.Credential{*credential}
			st.BootstrapHash = ""
			st.BootstrapExpires = time.Time{}
			st.Challenges = map[string]challenge{}
		} else {
			if len(st.Owner.Credentials) != 1 {
				return errDenied
			}
			parsed, err := protocol.ParseCredentialRequestResponseBytes(input.Credential)
			if err != nil {
				return errDenied
			}
			credential, err = wa.ValidateLogin(st.Owner, ch.Session, parsed)
			if err != nil {
				return errDenied
			}
			st.Owner.Credentials[0] = *credential
		}
		token, err := randomToken()
		if err != nil {
			return err
		}
		csrf, err := randomToken()
		if err != nil {
			return err
		}
		st.Sessions[digest(token)] = session{csrf, now.Add(sessionLifetime)}
		if err = commit(); err != nil {
			return err
		}
		newSession = token
		response = map[string]any{"authenticated": true, "csrfToken": csrf}
		return nil
	})
	if e != nil {
		return e
	}
	if newBinding != "" {
		setCookie(w, ceremonyCookie, newBinding, challengeLifetime)
	}
	if newSession != "" {
		setCookie(w, sessionCookie, newSession, sessionLifetime)
	}
	jsonResponse(w, 200, response)
	return nil
}
func (s *Service) inbox(w http.ResponseWriter, r *http.Request) error {
	if cookieValue(r, sessionCookie) == "" {
		if r.Method == "GET" && r.URL.Path == "/api/session" {
			jsonResponse(w, 200, map[string]bool{"authenticated": false})
			return nil
		}
		return errUnauthorized
	}
	var input struct {
		RequestID string `json:"requestId"`
		Text      string `json:"text"`
	}
	if r.Method == "POST" {
		if e := decodeBody(r, &input); e != nil {
			return e
		}
	}
	if (r.URL.Path == "/api/logout" && r.Method != "POST") || (r.URL.Path != "/api/requests" && r.URL.Path != "/api/logout" && r.Method != "GET") {
		return errInvalid
	}
	var response any
	e := transact(s.Directory, s.now(), s.afterRename, func(st *state, commit func() error) error {
		token := cookieValue(r, sessionCookie)
		session, authenticated := st.Sessions[digest(token)]
		authenticated = authenticated && token != ""
		if r.URL.Path == "/api/session" {
			if authenticated {
				response = map[string]any{"authenticated": true, "csrfToken": session.CSRF}
			} else {
				response = map[string]any{"authenticated": false}
			}
			return nil
		}
		if !authenticated {
			return errUnauthorized
		}
		if r.Method == "POST" && !equal(r.Header.Get("X-CSRF-Token"), session.CSRF) {
			return errDenied
		}
		switch r.URL.Path {
		case "/api/logout":
			delete(st.Sessions, digest(token))
			response = map[string]bool{"authenticated": false}
			return commit()
		case "/api/requests":
			if r.Method == "POST" {
				record, e := addRequest(st, input.RequestID, input.Text, s.now())
				if e != nil {
					return e
				}
				response = map[string]any{"request": record}
				return commit()
			}
			records := append([]requestRecord{}, st.Requests...)
			for i, j := 0, len(records)-1; i < j; i, j = i+1, j-1 {
				records[i], records[j] = records[j], records[i]
			}
			response = map[string]any{"requests": records}
		case "/api/export":
			response = map[string]any{"version": 1, "requests": st.Requests}
		}
		return nil
	})
	if e != nil {
		return e
	}
	if r.URL.Path == "/api/logout" {
		http.SetCookie(w, &http.Cookie{Name: sessionCookie, Path: "/", Secure: true, HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: -1})
	}
	if r.URL.Path == "/api/export" {
		w.Header().Set("Content-Disposition", `attachment; filename="bhakti-requests.json"`)
	}
	jsonResponse(w, 200, response)
	return nil
}
