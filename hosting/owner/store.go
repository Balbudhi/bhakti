package main

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"github.com/go-webauthn/webauthn/webauthn"
)

const (
	maxText      = 64 << 10
	maxRequests  = 1000
	maxAggregate = 16 << 20
	// JSON can encode one text byte as six bytes (e.g. a control character).
	maxStateBytes     = 100 << 20
	challengeLifetime = 5 * time.Minute
	sessionLifetime   = 30 * 24 * time.Hour
	maxChallenges     = 64
	maxSessions       = 64
)

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
var errDenied = &apiError{403, "Access was not granted. Please try again."}
var errUnauthorized = &apiError{401, "Sign in with your passkey."}
var errCapacity = &apiError{429, "Capacity reached. Please try again later."}
var errInvalid = &apiError{400, "Check the request and try again."}

type apiError struct {
	status  int
	message string
}

func (e *apiError) Error() string { return e.message }

type owner struct {
	ID          string                `json:"id"`
	Credentials []webauthn.Credential `json:"credentials"`
}

func (o owner) WebAuthnID() []byte                         { return []byte(o.ID) }
func (o owner) WebAuthnName() string                       { return "owner" }
func (o owner) WebAuthnDisplayName() string                { return "Bhakti owner" }
func (o owner) WebAuthnCredentials() []webauthn.Credential { return o.Credentials }

type challenge struct {
	Kind    string               `json:"kind"`
	Binding string               `json:"binding"`
	Expires time.Time            `json:"expires"`
	Session webauthn.SessionData `json:"session"`
}
type session struct {
	CSRF    string    `json:"csrf"`
	Expires time.Time `json:"expires"`
}
type requestRecord struct {
	ID        string `json:"id"`
	Text      string `json:"text"`
	CreatedAt string `json:"createdAt"`
	Status    string `json:"status"`
}
type state struct {
	Version          int                  `json:"version"`
	Owner            owner                `json:"owner"`
	BootstrapHash    string               `json:"bootstrapHash"`
	BootstrapExpires time.Time            `json:"bootstrapExpires"`
	Challenges       map[string]challenge `json:"challenges"`
	Sessions         map[string]session   `json:"sessions"`
	Begins           []time.Time          `json:"begins"`
	Requests         []requestRecord      `json:"requests"`
}

func randomToken() (string, error) {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		return "", e
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
func digest(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}
func equal(a, b string) bool { return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1 }
func validToken(s string) bool {
	b, e := base64.RawURLEncoding.DecodeString(s)
	return e == nil && len(b) == 32 && base64.RawURLEncoding.EncodeToString(b) == s
}
func validHash(s string) bool {
	b, e := hex.DecodeString(s)
	return e == nil && len(b) == 32 && strings.ToLower(s) == s
}
func (s *state) validate() error {
	bad := errors.New("invalid private state")
	if s.Version != 1 || !validToken(s.Owner.ID) || len(s.Owner.Credentials) > 1 || s.Challenges == nil || s.Sessions == nil || s.Requests == nil || len(s.Challenges) > maxChallenges || len(s.Sessions) > maxSessions || len(s.Requests) > maxRequests || len(s.Begins) > 60 {
		return bad
	}
	if len(s.Owner.Credentials) == 0 {
		if !validHash(s.BootstrapHash) || s.BootstrapExpires.IsZero() {
			return bad
		}
	} else {
		if s.BootstrapHash != "" || !s.BootstrapExpires.IsZero() {
			return bad
		}
		c := s.Owner.Credentials[0]
		if len(c.ID) == 0 || len(c.PublicKey) == 0 {
			return bad
		}
	}
	for k, c := range s.Challenges {
		if !validHash(k) || !validHash(c.Binding) || (c.Kind != "setup" && c.Kind != "auth") || c.Expires.IsZero() || c.Session.Challenge == "" {
			return bad
		}
	}
	for k, c := range s.Sessions {
		if !validHash(k) || !validToken(c.CSRF) || c.Expires.IsZero() {
			return bad
		}
	}
	seen := map[string]bool{}
	total := 0
	for _, r := range s.Requests {
		if !uuidPattern.MatchString(r.ID) || seen[r.ID] || !validText(r.Text) || r.Status != "queued" {
			return bad
		}
		if _, e := time.Parse(time.RFC3339Nano, r.CreatedAt); e != nil {
			return bad
		}
		seen[r.ID] = true
		total += len(r.Text)
	}
	if total > maxAggregate {
		return bad
	}
	return nil
}
func validText(s string) bool {
	return utf8.ValidString(s) && len(s) <= maxText && strings.TrimSpace(s) != ""
}
func (s *state) prune(now time.Time) {
	for id, c := range s.Challenges {
		if !now.Before(c.Expires) {
			delete(s.Challenges, id)
		}
	}
	for id, c := range s.Sessions {
		if !now.Before(c.Expires) {
			delete(s.Sessions, id)
		}
	}
	recent := s.Begins[:0]
	for _, t := range s.Begins {
		if !t.After(now) && now.Sub(t) < time.Minute {
			recent = append(recent, t)
		}
	}
	s.Begins = recent
}
func checkPrivate(info os.FileInfo, directory bool) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() || info.Mode().Perm()&0077 != 0 || info.Mode()&os.ModeSymlink != 0 || (directory && !info.IsDir()) || (!directory && !info.Mode().IsRegular()) {
		return errors.New("unsafe private storage")
	}
	return nil
}
func lockDirectory(dir string) (func(), error) {
	if !filepath.IsAbs(dir) {
		return nil, errors.New("private directory must be absolute")
	}
	info, e := os.Lstat(dir)
	if e != nil {
		return nil, e
	}
	if e = checkPrivate(info, true); e != nil {
		return nil, e
	}
	fd, e := syscall.Open(filepath.Join(dir, "state.lock"), syscall.O_RDWR|syscall.O_CREAT|syscall.O_NOFOLLOW, 0600)
	if e != nil {
		return nil, e
	}
	f := os.NewFile(uintptr(fd), "state.lock")
	fail := func(e error) (func(), error) { f.Close(); return nil, e }
	info, e = f.Stat()
	if e != nil {
		return fail(e)
	}
	if e = checkPrivate(info, false); e != nil {
		return fail(e)
	}
	deadline := time.Now().Add(2 * time.Second)
	for {
		e = syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB)
		if e == nil {
			break
		}
		if e != syscall.EWOULDBLOCK && e != syscall.EAGAIN {
			return fail(e)
		}
		if !time.Now().Before(deadline) {
			return fail(errors.New("private storage busy"))
		}
		time.Sleep(10 * time.Millisecond)
	}
	return func() { syscall.Flock(fd, syscall.LOCK_UN); f.Close() }, nil
}
func readState(dir string) (*state, error) {
	fd, e := syscall.Open(filepath.Join(dir, "state.json"), syscall.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if e != nil {
		return nil, e
	}
	f := os.NewFile(uintptr(fd), "state.json")
	defer f.Close()
	info, e := f.Stat()
	if e != nil {
		return nil, e
	}
	if e = checkPrivate(info, false); e != nil {
		return nil, e
	}
	if info.Size() > maxStateBytes {
		return nil, errors.New("private state too large")
	}
	decoder := json.NewDecoder(io.LimitReader(f, maxStateBytes+1))
	decoder.DisallowUnknownFields()
	var s state
	if e = decoder.Decode(&s); e != nil {
		return nil, e
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return nil, errors.New("trailing private state")
	}
	if e = s.validate(); e != nil {
		return nil, e
	}
	return &s, nil
}

// atomicState acknowledges only after both file and directory are synchronized.
// A failure after rename is an unknown outcome; retry by the same request ID.
func atomicState(dir string, s *state, afterRename func() error) error {
	if e := s.validate(); e != nil {
		return e
	}
	f, e := os.CreateTemp(dir, ".state-*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	defer f.Close()
	encoder := json.NewEncoder(f)
	encoder.SetEscapeHTML(false)
	if e = encoder.Encode(s); e != nil {
		return e
	}
	if e = f.Sync(); e != nil {
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	if e = os.Rename(name, filepath.Join(dir, "state.json")); e != nil {
		return e
	}
	if afterRename != nil {
		if e = afterRename(); e != nil {
			return e
		}
	}
	d, e := os.Open(dir)
	if e != nil {
		return e
	}
	defer d.Close()
	return d.Sync()
}
func transact(dir string, now time.Time, afterRename func() error, fn func(*state, func() error) error) error {
	unlock, e := lockDirectory(dir)
	if e != nil {
		return e
	}
	defer unlock()
	s, e := readState(dir)
	if e != nil {
		return e
	}
	s.prune(now)
	return fn(s, func() error { return atomicState(dir, s, afterRename) })
}
func provisionBootstrap(dir string, now time.Time) (string, error) {
	if !filepath.IsAbs(dir) {
		return "", errors.New("private directory must be absolute")
	}
	if e := os.MkdirAll(dir, 0700); e != nil {
		return "", e
	}
	unlock, e := lockDirectory(dir)
	if e != nil {
		return "", e
	}
	defer unlock()
	s, e := readState(dir)
	if os.IsNotExist(e) {
		id, err := randomToken()
		if err != nil {
			return "", err
		}
		s = &state{Version: 1, Owner: owner{ID: id, Credentials: []webauthn.Credential{}}, Challenges: map[string]challenge{}, Sessions: map[string]session{}, Begins: []time.Time{}, Requests: []requestRecord{}}
	} else if e != nil {
		return "", e
	}
	if len(s.Owner.Credentials) != 0 {
		return "", errors.New("owner already enrolled")
	}
	code, e := randomToken()
	if e != nil {
		return "", e
	}
	s.BootstrapHash = digest(code)
	s.BootstrapExpires = now.Add(24 * time.Hour)
	s.Challenges = map[string]challenge{}
	s.Begins = []time.Time{}
	if e = atomicState(dir, s, nil); e != nil {
		return "", e
	}
	return code, nil
}
func exportRequests(dir string, now time.Time) ([]byte, error) {
	var result []byte
	e := transact(dir, now, nil, func(s *state, _ func() error) error {
		var e error
		result, e = json.Marshal(struct {
			Version  int             `json:"version"`
			Requests []requestRecord `json:"requests"`
		}{1, s.Requests})
		return e
	})
	return result, e
}
func addRequest(s *state, id, text string, now time.Time) (requestRecord, error) {
	if !uuidPattern.MatchString(id) || !validText(text) {
		return requestRecord{}, errInvalid
	}
	total := 0
	for _, r := range s.Requests {
		if r.ID == id {
			if r.Text != text {
				return requestRecord{}, &apiError{409, "This request ID already contains different text."}
			}
			return r, nil
		}
		total += len(r.Text)
	}
	if len(s.Requests) >= maxRequests || total+len(text) > maxAggregate {
		return requestRecord{}, &apiError{507, "Your inbox is full. Export it before arranging more storage."}
	}
	r := requestRecord{id, text, now.UTC().Format(time.RFC3339Nano), "queued"}
	s.Requests = append(s.Requests, r)
	return r, nil
}
