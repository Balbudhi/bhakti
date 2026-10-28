package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/fxamacker/cbor/v2"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// Real HTTP, P-256 signatures and filesystem transactions; this authenticator
// constructs the standard wire format independently of the service verifier.
const testHost = "owner.bhakti.eeshan.xyz"
const testOrigin = "https://" + testHost

type browser struct {
	t       *testing.T
	service *Service
	cookies map[string]*http.Cookie
	csrf    string
}

func fixture(t *testing.T) (*browser, string, *time.Time) {
	t.Helper()
	dir := t.TempDir()
	if e := os.Chmod(dir, 0700); e != nil {
		t.Fatal(e)
	}
	now := time.Date(2026, 10, 27, 12, 0, 0, 0, time.UTC)
	code, e := provisionBootstrap(dir, now)
	if e != nil {
		t.Fatal(e)
	}
	return &browser{t: t, service: &Service{Directory: dir, Now: func() time.Time { return now }}, cookies: map[string]*http.Cookie{}}, code, &now
}
func (b *browser) request(method, path string, body any) *httptest.ResponseRecorder {
	var data []byte
	if body != nil {
		data = jsonBytes(b.t, body)
	}
	r := httptest.NewRequest(method, testOrigin+path, bytes.NewReader(data))
	if method == "POST" {
		r.Header.Set("Origin", testOrigin)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("X-CSRF-Token", b.csrf)
	}
	for _, c := range b.cookies {
		r.AddCookie(c)
	}
	w := httptest.NewRecorder()
	b.service.ServeHTTP(w, r)
	for _, c := range w.Result().Cookies() {
		if c.MaxAge < 0 {
			delete(b.cookies, c.Name)
		} else {
			b.cookies[c.Name] = c
		}
	}
	return w
}
func decode(t *testing.T, w *httptest.ResponseRecorder, status int) map[string]any {
	t.Helper()
	if w.Code != status {
		t.Fatalf("HTTP %d wanted %d: %s", w.Code, status, w.Body.String())
	}
	var out map[string]any
	if e := json.Unmarshal(w.Body.Bytes(), &out); e != nil {
		t.Fatal(e)
	}
	return out
}
func (b *browser) begin(kind, code string) map[string]any {
	return decode(b.t, b.request("POST", "/api/"+kind+"/begin", map[string]any{"code": code}), 200)
}
func (b *browser) finish(kind, code string, begin, cred map[string]any) *httptest.ResponseRecorder {
	return b.request("POST", "/api/"+kind+"/finish", map[string]any{"code": code, "challengeId": begin["challengeId"], "credential": cred})
}
func (b *browser) enroll(code string) authenticator {
	a := newAuthenticator(b.t)
	begin := b.begin("setup", code)
	got := decode(b.t, b.finish("setup", code, begin, a.response(b.t, begin, true, testOrigin, testHost, 0x45, 0)), 200)
	b.csrf = got["csrfToken"].(string)
	return a
}

type authenticator struct {
	key *ecdsa.PrivateKey
	id  []byte
}

func newAuthenticator(t *testing.T) authenticator {
	t.Helper()
	key, e := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if e != nil {
		t.Fatal(e)
	}
	id := make([]byte, 32)
	if _, e = rand.Read(id); e != nil {
		t.Fatal(e)
	}
	return authenticator{key, id}
}
func b64(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }
func jsonBytes(t *testing.T, v any) []byte {
	t.Helper()
	b, e := json.Marshal(v)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func (a authenticator) response(t *testing.T, begin map[string]any, registration bool, origin, rp string, flags byte, count uint32) map[string]any {
	kind := "webauthn.get"
	if registration {
		kind = "webauthn.create"
	}
	client := jsonBytes(t, map[string]any{"type": kind, "challenge": begin["publicKey"].(map[string]any)["challenge"], "origin": origin, "crossOrigin": false})
	rpHash := sha256.Sum256([]byte(rp))
	auth := append([]byte{}, rpHash[:]...)
	auth = append(auth, flags)
	auth = binary.BigEndian.AppendUint32(auth, count)
	response := map[string]any{"clientDataJSON": b64(client)}
	if registration {
		cose, e := cbor.Marshal(map[int]any{1: 2, 3: -7, -1: 1, -2: a.key.X.FillBytes(make([]byte, 32)), -3: a.key.Y.FillBytes(make([]byte, 32))})
		if e != nil {
			t.Fatal(e)
		}
		auth = append(auth, make([]byte, 16)...)
		auth = binary.BigEndian.AppendUint16(auth, uint16(len(a.id)))
		auth = append(auth, a.id...)
		auth = append(auth, cose...)
		att, e := cbor.Marshal(map[string]any{"fmt": "none", "attStmt": map[string]any{}, "authData": auth})
		if e != nil {
			t.Fatal(e)
		}
		response["attestationObject"] = b64(att)
		response["transports"] = []string{"internal"}
	} else {
		ch := sha256.Sum256(client)
		signed := append(append([]byte{}, auth...), ch[:]...)
		h := sha256.Sum256(signed)
		sig, e := ecdsa.SignASN1(rand.Reader, a.key, h[:])
		if e != nil {
			t.Fatal(e)
		}
		response["authenticatorData"] = b64(auth)
		response["signature"] = b64(sig)
	}
	return map[string]any{"id": b64(a.id), "rawId": b64(a.id), "type": "public-key", "response": response, "clientExtensionResults": map[string]any{}}
}
func TestEnrollmentLoginAndReplay(t *testing.T) {
	b, code, now := fixture(t)
	a := b.enroll(code)
	for _, c := range b.cookies {
		if !c.Secure || !c.HttpOnly || c.SameSite != http.SameSiteStrictMode || c.Domain != "" || c.Path != "/" {
			t.Fatal("unsafe cookie", c)
		}
	}
	if got := decode(t, b.request("GET", "/api/session", nil), 200); got["authenticated"] != true {
		t.Fatal(got)
	}
	decode(t, b.request("POST", "/api/logout", map[string]any{}), 200)
	begin := b.begin("auth", "")
	options := begin["publicKey"].(map[string]any)
	if options["userVerification"] != "required" || options["rpId"] != testHost {
		t.Fatal(options)
	}
	cred := a.response(t, begin, false, testOrigin, testHost, 5, 0)
	got := decode(t, b.finish("auth", "", begin, cred), 200)
	b.csrf = got["csrfToken"].(string)
	decode(t, b.finish("auth", "", begin, cred), 403)
	*now = now.Add(31 * 24 * time.Hour)
	if got := decode(t, b.request("GET", "/api/session", nil), 200); got["authenticated"] != false {
		t.Fatal("expired session", got)
	}
	for _, name := range []string{"state.json", "state.lock"} {
		info, e := os.Stat(filepath.Join(b.service.Directory, name))
		if e != nil || info.Mode().Perm() != 0600 {
			t.Fatal("permissions", name, e)
		}
	}
}
func TestCryptographicRejectionsConsumeChallenge(t *testing.T) {
	for _, name := range []string{"origin", "rp", "uv", "signature", "credential", "challenge", "expired"} {
		t.Run(name, func(t *testing.T) {
			b, code, now := fixture(t)
			a := b.enroll(code)
			begin := b.begin("auth", "")
			origin, rp, flags := testOrigin, testHost, byte(5)
			signer := a
			switch name {
			case "origin":
				origin = "https://evil.example"
			case "rp":
				rp = "bhakti.eeshan.xyz"
			case "uv":
				flags = 1
			case "signature":
				signer.key = newAuthenticator(t).key
			case "credential":
				signer = newAuthenticator(t)
			case "expired":
				*now = now.Add(6 * time.Minute)
			}
			rb := begin
			if name == "challenge" {
				rb = map[string]any{"publicKey": map[string]any{"challenge": b64([]byte("wrong challenge"))}}
			}
			decode(t, b.finish("auth", "", begin, signer.response(t, rb, false, origin, rp, flags, 0)), 403)
			decode(t, b.finish("auth", "", begin, a.response(t, begin, false, testOrigin, testHost, 5, 0)), 403)
		})
	}
}
func TestBootstrapCodeAndEnrollmentRace(t *testing.T) {
	b, code, _ := fixture(t)
	decode(t, b.request("POST", "/api/setup/begin", map[string]any{"code": "wrong"}), 403)
	one := b.begin("setup", code)
	a, c := newAuthenticator(t), newAuthenticator(t)
	other := &browser{t: t, service: &Service{Directory: b.service.Directory, Now: b.service.Now}, cookies: map[string]*http.Cookie{}}
	two := other.begin("setup", code)
	var wg sync.WaitGroup
	codes := make(chan int, 2)
	for _, x := range []struct {
		client *browser
		begin  map[string]any
		auth   authenticator
	}{{b, one, a}, {other, two, c}} {
		wg.Add(1)
		go func(x struct {
			client *browser
			begin  map[string]any
			auth   authenticator
		}) {
			defer wg.Done()
			codes <- x.client.finish("setup", code, x.begin, x.auth.response(t, x.begin, true, testOrigin, testHost, 0x45, 0)).Code
		}(x)
	}
	wg.Wait()
	close(codes)
	ok, denied := 0, 0
	for n := range codes {
		if n == 200 {
			ok++
		} else if n == 403 {
			denied++
		} else {
			t.Fatal(n)
		}
	}
	if ok != 1 || denied != 1 {
		t.Fatal(ok, denied)
	}
	if _, e := provisionBootstrap(b.service.Directory, b.service.Now()); e == nil {
		t.Fatal("bootstrap reopened")
	}
	decode(t, b.request("POST", "/api/setup/begin", map[string]any{"code": code}), 403)
}
func TestRequestDurabilityIdempotenceAndIsolation(t *testing.T) {
	b, code, _ := fixture(t)
	for _, path := range []string{"/api/requests", "/api/export"} {
		decode(t, b.request("GET", path, nil), 401)
	}
	decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": "9a2e8184-269f-4c49-a517-7cc3f3231d78", "text": "private"}), 401)
	b.enroll(code)
	text := "  ॐ Śiva\nhttps://youtu.be/example\r\n<script>private</script>\t"
	input := map[string]any{"requestId": "9a2e8184-269f-4c49-a517-7cc3f3231d78", "text": text}
	first := decode(t, b.request("POST", "/api/requests", input), 200)
	if first["request"].(map[string]any)["text"] != text {
		t.Fatal("text changed")
	}
	b.service = &Service{Directory: b.service.Directory, Now: b.service.Now}
	second := decode(t, b.request("POST", "/api/requests", input), 200)
	if !bytes.Equal(jsonBytes(t, first), jsonBytes(t, second)) {
		t.Fatal("retry changed request")
	}
	input["text"] = "different"
	decode(t, b.request("POST", "/api/requests", input), 409)
	got := decode(t, b.request("GET", "/api/requests", nil), 200)["requests"].([]any)
	if len(got) != 1 || got[0].(map[string]any)["text"] != text {
		t.Fatal(got)
	}
	exported, e := exportRequests(b.service.Directory, b.service.Now())
	if e != nil {
		t.Fatal(e)
	}
	if !bytes.Contains(exported, []byte("Śiva")) {
		t.Fatal("missing exported unicode")
	}
	old := b.csrf
	b.csrf = "wrong"
	decode(t, b.request("POST", "/api/requests", input), 403)
	b.csrf = old
	for _, bad := range []any{map[string]any{"requestId": "bad", "text": "x"}, map[string]any{"requestId": "ef9c9bab-7732-4d6b-a5bf-18c203c11734", "text": " \n"}, map[string]any{"requestId": "ef9c9bab-7732-4d6b-a5bf-18c203c11734", "text": strings.Repeat("x", 65537)}} {
		decode(t, b.request("POST", "/api/requests", bad), 400)
	}
}
func TestOriginHostAndForwardingBoundaries(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	for _, kind := range []string{"host", "origin", "missing-origin", "forwarded", "proto", "insecure"} {
		t.Run(kind, func(t *testing.T) {
			r := httptest.NewRequest("POST", testOrigin+"/api/logout", strings.NewReader("{}"))
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set("Origin", testOrigin)
			r.Header.Set("X-CSRF-Token", b.csrf)
			for _, c := range b.cookies {
				r.AddCookie(c)
			}
			switch kind {
			case "host":
				r.Host = "evil.example"
			case "origin":
				r.Header.Set("Origin", "https://bhakti.eeshan.xyz")
			case "missing-origin":
				r.Header.Del("Origin")
			case "forwarded":
				r.Header.Set("Forwarded", "host="+testHost)
			case "proto":
				r.Header.Set("X-Forwarded-Proto", "https")
			case "insecure":
				r.TLS = nil
				r.URL.Scheme = "http"
			}
			w := httptest.NewRecorder()
			b.service.ServeHTTP(w, r)
			if w.Code != 403 {
				t.Fatal(kind, w.Code)
			}
		})
	}
}
func TestConcurrentSubmissionsAndStorageFailure(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			c := &browser{t: t, service: &Service{Directory: b.service.Directory, Now: b.service.Now}, cookies: b.cookies, csrf: b.csrf}
			w := c.request("POST", "/api/requests", map[string]any{"requestId": fmt.Sprintf("00000000-0000-4000-8000-%012d", i), "text": fmt.Sprintf("song %d", i)})
			if w.Code != 200 {
				t.Errorf("concurrent %d %s", w.Code, w.Body.String())
			}
		}(i)
	}
	wg.Wait()
	if got := decode(t, b.request("GET", "/api/requests", nil), 200)["requests"].([]any); len(got) != 12 {
		t.Fatal(len(got))
	}
	if e := os.WriteFile(filepath.Join(b.service.Directory, "state.json"), []byte("{broken"), 0600); e != nil {
		t.Fatal(e)
	}
	if w := b.request("POST", "/api/requests", map[string]any{"requestId": "00000000-0000-4000-8000-000000000099", "text": "must not be acknowledged"}); w.Code != 503 {
		t.Fatal(w.Code)
	}
}

func TestBootstrapReplacementExpiryAndSecretStorage(t *testing.T) {
	b, old, now := fixture(t)
	*now = now.Add(25 * time.Hour)
	decode(t, b.request("POST", "/api/setup/begin", map[string]any{"code": old}), 403)
	replacement, e := provisionBootstrap(b.service.Directory, *now)
	if e != nil {
		t.Fatal(e)
	}
	decode(t, b.request("POST", "/api/setup/begin", map[string]any{"code": old}), 403)
	b.enroll(replacement)
	data, e := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	for _, secret := range []string{old, replacement, b.cookies["__Host-bhakti-session"].Value} {
		if bytes.Contains(data, []byte(secret)) {
			t.Fatal("raw authentication secret stored")
		}
	}
}
func TestRegistrationVerificationAndCeremonyBinding(t *testing.T) {
	for _, name := range []string{"origin", "rp", "uv", "challenge", "cookie", "code"} {
		t.Run(name, func(t *testing.T) {
			b, code, _ := fixture(t)
			begin := b.begin("setup", code)
			a := newAuthenticator(t)
			origin, rp, flags := testOrigin, testHost, byte(0x45)
			sentcode := code
			responseBegin := begin
			switch name {
			case "origin":
				origin = "https://evil.example"
			case "rp":
				rp = "eeshan.xyz"
			case "uv":
				flags = 0x41
			case "challenge":
				responseBegin = map[string]any{"publicKey": map[string]any{"challenge": b64([]byte("wrong"))}}
			case "cookie":
				b.cookies = map[string]*http.Cookie{}
			case "code":
				sentcode = "wrong"
			}
			decode(t, b.finish("setup", sentcode, begin, a.response(t, responseBegin, true, origin, rp, flags, 0)), 403)
			// A failed registration must not establish an owner or revoke a valid bootstrap code.
			b.enroll(code)
		})
	}
}

// This helper runs the same HTTP handler in an independent OS process. Its
// private directory and HTTP input are test-only stdin, never production flags.
func TestProcessHelper(t *testing.T) {
	if os.Getenv("BHAKTI_TEST_PROCESS") != "1" {
		return
	}
	var input struct {
		Directory string
		Now       time.Time
		Path      string
		Body      json.RawMessage
		Cookies   string
		CSRF      string
	}
	if e := json.NewDecoder(os.Stdin).Decode(&input); e != nil {
		t.Fatal(e)
	}
	r := httptest.NewRequest("POST", testOrigin+input.Path, bytes.NewReader(input.Body))
	r.Header.Set("Origin", testOrigin)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Cookie", input.Cookies)
	r.Header.Set("X-CSRF-Token", input.CSRF)
	w := httptest.NewRecorder()
	(&Service{Directory: input.Directory, Now: func() time.Time { return input.Now }}).ServeHTTP(w, r)
	json.NewEncoder(os.Stdout).Encode(map[string]any{"status": w.Code, "body": json.RawMessage(w.Body.Bytes())})
	os.Exit(0)
}
func processRequest(t *testing.T, b *browser, path string, body any) int {
	t.Helper()
	var cookieparts []string
	for _, c := range b.cookies {
		cookieparts = append(cookieparts, c.Name+"="+c.Value)
	}
	input := map[string]any{"Directory": b.service.Directory, "Now": b.service.Now(), "Path": path, "Body": body, "Cookies": strings.Join(cookieparts, "; "), "CSRF": b.csrf}
	cmd := exec.Command(os.Args[0], "-test.run=^TestProcessHelper$")
	cmd.Env = append(os.Environ(), "BHAKTI_TEST_PROCESS=1")
	cmd.Stdin = bytes.NewReader(jsonBytes(t, input))
	out, e := cmd.CombinedOutput()
	if e != nil {
		t.Errorf("helper: %v %s", e, out)
		return 0
	}
	var result struct{ Status int }
	if e = json.Unmarshal(out, &result); e != nil {
		t.Errorf("helper JSON: %s", out)
		return 0
	}
	return result.Status
}
func TestEnrollmentAcrossProcesses(t *testing.T) {
	b, code, _ := fixture(t)
	other := &browser{t: t, service: b.service, cookies: map[string]*http.Cookie{}}
	one, two := b.begin("setup", code), other.begin("setup", code)
	a, c := newAuthenticator(t), newAuthenticator(t)
	var wg sync.WaitGroup
	statuses := make(chan int, 2)
	for _, x := range []struct {
		b     *browser
		begin map[string]any
		a     authenticator
	}{{b, one, a}, {other, two, c}} {
		wg.Add(1)
		go func(x struct {
			b     *browser
			begin map[string]any
			a     authenticator
		}) {
			defer wg.Done()
			statuses <- processRequest(t, x.b, "/api/setup/finish", map[string]any{"code": code, "challengeId": x.begin["challengeId"], "credential": x.a.response(t, x.begin, true, testOrigin, testHost, 0x45, 0)})
		}(x)
	}
	wg.Wait()
	close(statuses)
	counts := map[int]int{}
	for status := range statuses {
		counts[status]++
	}
	if counts[200] != 1 || counts[403] != 1 {
		t.Fatal(counts)
	}
}

func TestPristineServiceSignedOut(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	b := &browser{t: t, service: &Service{Directory: dir}, cookies: map[string]*http.Cookie{}}
	if got := decode(t, b.request("GET", "/api/session", nil), 200); got["authenticated"] != false {
		t.Fatal(got)
	}
	decode(t, b.request("GET", "/api/requests", nil), 401)
	if _, e := os.Stat(dir); !os.IsNotExist(e) {
		t.Fatal("public read created private state", e)
	}
}
func TestCapacityPreservesRequestsAndAllowsExactRetries(t *testing.T) {
	for _, kind := range []string{"count", "bytes"} {
		t.Run(kind, func(t *testing.T) {
			b, code, _ := fixture(t)
			b.enroll(code)
			count, text := 1000, "x"
			if kind == "bytes" {
				count = 256
				text = strings.Repeat("x", 65536)
			}
			e := transact(b.service.Directory, b.service.Now(), nil, func(s *state, commit func() error) error {
				for i := 0; i < count; i++ {
					s.Requests = append(s.Requests, requestRecord{fmt.Sprintf("00000000-0000-4000-8000-%012d", i), text, b.service.Now().Format(time.RFC3339), "queued"})
				}
				return commit()
			})
			if e != nil {
				t.Fatal(e)
			}
			decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": "eeeeeeee-0000-4000-8000-000000000001", "text": "over capacity"}), 507)
			decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": "00000000-0000-4000-8000-000000000000", "text": text}), 200)
			data, e := exportRequests(b.service.Directory, b.service.Now())
			if e != nil {
				t.Fatal(e)
			}
			var exported struct{ Requests []requestRecord }
			if e = json.Unmarshal(data, &exported); e != nil || len(exported.Requests) != count {
				t.Fatal("capacity lost requests", e, len(exported.Requests))
			}
		})
	}
}
func TestDurabilityFailureAndRetry(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	input := map[string]any{"requestId": "00000000-0000-4000-8000-000000000001", "text": "do not duplicate after ambiguous commit"}
	b.service.afterRename = func() error { return errors.New("directory sync failed") }
	decode(t, b.request("POST", "/api/requests", input), 503)
	b.service = &Service{Directory: b.service.Directory, Now: b.service.Now}
	decode(t, b.request("POST", "/api/requests", input), 200)
	if requests := decode(t, b.request("GET", "/api/requests", nil), 200)["requests"].([]any); len(requests) != 1 {
		t.Fatal("duplicated after unknown outcome")
	}
	if e := os.Chmod(b.service.Directory, 0500); e != nil {
		t.Fatal(e)
	}
	input["requestId"] = "00000000-0000-4000-8000-000000000002"
	w := b.request("POST", "/api/requests", input)
	if e := os.Chmod(b.service.Directory, 0700); e != nil {
		t.Fatal(e)
	}
	decode(t, w, 503)
	decode(t, b.request("POST", "/api/requests", input), 200)
	if requests := decode(t, b.request("GET", "/api/requests", nil), 200)["requests"].([]any); len(requests) != 2 {
		t.Fatal("lost retry")
	}
}
func TestCorruptStateCannotReopenBootstrap(t *testing.T) {
	for _, corrupt := range []string{`{}`, `{"version":1}`, `null`} {
		t.Run(corrupt, func(t *testing.T) {
			b, _, _ := fixture(t)
			if e := os.WriteFile(filepath.Join(b.service.Directory, "state.json"), []byte(corrupt), 0600); e != nil {
				t.Fatal(e)
			}
			if _, e := provisionBootstrap(b.service.Directory, b.service.Now()); e == nil {
				t.Fatal("corrupt state replaced")
			}
			decode(t, b.request("POST", "/api/setup/begin", map[string]string{"code": "wrong"}), 503)
		})
	}
}
func TestSessionAndChallengeCapacity(t *testing.T) {
	b, code, now := fixture(t)
	a := b.enroll(code)
	if e := transact(b.service.Directory, *now, nil, func(s *state, commit func() error) error {
		for len(s.Sessions) < maxSessions {
			token, e := randomToken()
			if e != nil {
				return e
			}
			csrf, e := randomToken()
			if e != nil {
				return e
			}
			s.Sessions[digest(token)] = session{csrf, now.Add(sessionLifetime)}
		}
		return commit()
	}); e != nil {
		t.Fatal(e)
	}
	begin := b.begin("auth", "")
	decode(t, b.finish("auth", "", begin, a.response(t, begin, false, testOrigin, testHost, 5, 0)), 429)
	// Expiration restores capacity without evicting a valid session to admit strangers.
	*now = now.Add(sessionLifetime + time.Second)
	begin = b.begin("auth", "")
	decode(t, b.finish("auth", "", begin, a.response(t, begin, false, testOrigin, testHost, 5, 0)), 200)
	for i := 0; i < 59; i++ {
		b.begin("auth", "")
	}
	decode(t, b.request("POST", "/api/auth/begin", map[string]any{}), 429)
	*now = now.Add(6 * time.Minute)
	b.begin("auth", "")
}

func TestCeremonyCookieRenewal(t *testing.T) {
	b, code, now := fixture(t)
	b.begin("setup", code)
	binding := b.cookies[ceremonyCookie].Value
	*now = now.Add(295 * time.Second)
	w := b.request("POST", "/api/setup/begin", map[string]string{"code": code})
	decode(t, w, 200)
	renewed := false
	for _, c := range w.Result().Cookies() {
		if c.Name == ceremonyCookie && c.Value == binding && c.MaxAge == 300 {
			renewed = true
		}
	}
	if !renewed {
		t.Fatal("retry did not renew ceremony cookie window")
	}
}
func TestCGIHelper(t *testing.T) {
	if os.Getenv("BHAKTI_TEST_CGI") != "1" {
		return
	}
	privateDirectory = os.Getenv("BHAKTI_TEST_STATE")
	main()
	os.Exit(0)
}
func TestCGICannotInvokeAdministration(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	before, e := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	for _, operation := range []string{"-init", "-export"} {
		cmd := exec.Command(os.Args[0], "-test.run=^TestCGIHelper$", "--", operation, "-state", b.service.Directory)
		cmd.Env = []string{"BHAKTI_TEST_CGI=1", "BHAKTI_TEST_STATE=" + b.service.Directory, "GATEWAY_INTERFACE=CGI/1.1", "REQUEST_METHOD=GET", "SERVER_PROTOCOL=HTTP/1.1", "SERVER_NAME=" + testHost, "HTTP_HOST=" + testHost, "SERVER_PORT=443", "HTTPS=on", "SCRIPT_NAME=/owner.cgi", "REQUEST_URI=/api/requests?" + operation, "QUERY_STRING=" + operation}
		out, e := cmd.CombinedOutput()
		if e != nil {
			t.Fatalf("CGI failed: %v %s", e, out)
		}
		if !bytes.Contains(out, []byte("Status: 401")) || bytes.Contains(out, []byte(`"requests"`)) {
			t.Fatalf("CGI administration route: %s", out)
		}
	}
	after, e := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if e != nil || !bytes.Equal(before, after) {
		t.Fatal("CGI query mutated private state", e)
	}
}
func TestStaticOwnerAssets(t *testing.T) {
	b, _, _ := fixture(t)
	for _, path := range []string{"/", "/setup", "/owner.css", "/owner.js", "/fonts/cormorant-garamond-latin.woff2", "/fonts/inter-latin-ext.woff2", "/fonts/inter-latin.woff2", "/fonts/inter-OFL.txt", "/fonts/cormorantgaramond-OFL.txt", "/fonts/SOURCES.txt"} {
		w := b.request("GET", path, nil)
		if w.Code != 200 || w.Body.Len() == 0 {
			t.Fatal(path, w.Code)
		}
		if !strings.Contains(w.Header().Get("Cache-Control"), "no-store") {
			t.Fatal("cacheable owner response")
		}
	}
	if w := b.request("GET", "/state.json", nil); w.Code != 404 {
		t.Fatal("unexpected public state route", w.Code)
	}
}

func TestSyncedPasskeyCountersAndServerLogout(t *testing.T) {
	b, code, _ := fixture(t)
	a := newAuthenticator(t)
	begin := b.begin("setup", code)
	got := decode(t, b.finish("setup", code, begin, a.response(t, begin, true, testOrigin, testHost, 0x5d, 0)), 200)
	b.csrf = got["csrfToken"].(string)
	for _, counter := range []uint32{0, 1, 1} {
		begin = b.begin("auth", "")
		got = decode(t, b.finish("auth", "", begin, a.response(t, begin, false, testOrigin, testHost, 0x1d, counter)), 200)
		b.csrf = got["csrfToken"].(string)
	}
	stolen := b.cookies[sessionCookie]
	decode(t, b.request("POST", "/api/logout", map[string]any{}), 200)
	b.cookies[sessionCookie] = stolen
	decode(t, b.request("GET", "/api/requests", nil), 401)
}
func TestBodyBoundsAndExactControlText(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	text := "ॐ" + strings.Repeat("\x00", 65533)
	input := map[string]any{"requestId": "00000000-0000-4000-8000-000000000001", "text": text}
	got := decode(t, b.request("POST", "/api/requests", input), 200)
	if got["request"].(map[string]any)["text"] != text {
		t.Fatal("maximum escaped text changed")
	}
	for _, raw := range [][]byte{[]byte(strings.Repeat(" ", 512<<10) + "{}"), append([]byte(`{"requestId":"00000000-0000-4000-8000-000000000002","text":"`), append([]byte{255}, []byte(`"}`)...)...)} {
		r := httptest.NewRequest("POST", testOrigin+"/api/requests", bytes.NewReader(raw))
		r.Header.Set("Origin", testOrigin)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("X-CSRF-Token", b.csrf)
		for _, c := range b.cookies {
			r.AddCookie(c)
		}
		w := httptest.NewRecorder()
		b.service.ServeHTTP(w, r)
		decode(t, w, 400)
	}
}

func TestCGIResponseFraming(t *testing.T) {
	b, _, _ := fixture(t)
	for _, oversized := range []bool{false, true} {
		r := httptest.NewRequest("POST", testOrigin+"/api/requests", strings.NewReader("{}"))
		r.Header.Set("Origin", testOrigin)
		r.Header.Set("Content-Type", "application/json")
		if oversized {
			r.ContentLength = (512 << 10) + 1
		}
		w := httptest.NewRecorder()
		b.service.ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatal(w.Code)
		}
		remaining, e := io.ReadAll(r.Body)
		if e != nil {
			t.Fatal(e)
		}
		if (!oversized && len(remaining) != 0) || (oversized && string(remaining) != "{}") {
			t.Fatal("incorrect bounded drain", oversized)
		}
		if w.Header().Get("Content-Length") != strconv.Itoa(w.Body.Len()) {
			t.Fatal("missing JSON byte boundary")
		}
	}
}
