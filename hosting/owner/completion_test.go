package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Completion is explicit and durable, never inferred from request text or catalogue.
// Tests exercise real authentication, HTTP, filesystem transactions, restart and CLI.
func TestCompletionDurabilityReplayAndIsolation(t *testing.T) {
	b, code, now := fixture(t)
	b.enroll(code)
	id := "11111111-1111-4111-8111-111111111111"
	input := map[string]any{"requestId": id, "text": "  ॐ\nhttps://example.test/song\t"}
	before := decode(t, b.request("POST", "/api/requests", input), 200)["request"].(map[string]any)
	if len(before) != 4 || before["status"] != "queued" {
		t.Fatal("legacy queued format changed", before)
	}
	other := map[string]any{"requestId": "22222222-2222-4222-8222-222222222222", "text": "leave pending"}
	untouched := decode(t, b.request("POST", "/api/requests", other), 200)["request"]
	*now = now.Add(time.Hour)
	result := decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": id}), 200)["request"].(map[string]any)
	for _, key := range []string{"id", "text", "createdAt"} {
		if result[key] != before[key] {
			t.Fatal("completion changed immutable field", key)
		}
	}
	if result["status"] != "completed" || result["completedAt"] != now.UTC().Format(time.RFC3339Nano) {
		t.Fatal(result)
	}
	b.service = &Service{Directory: b.service.Directory, Now: b.service.Now}
	*now = now.Add(time.Hour)
	retry := decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": id}), 200)["request"]
	replay := decode(t, b.request("POST", "/api/requests", input), 200)["request"]
	if !bytes.Equal(jsonBytes(t, result), jsonBytes(t, retry)) || !bytes.Equal(jsonBytes(t, result), jsonBytes(t, replay)) {
		t.Fatal("completion or creation replay changed completed record")
	}
	records := decode(t, b.request("GET", "/api/requests", nil), 200)["requests"].([]any)
	if len(records) != 2 || !bytes.Equal(jsonBytes(t, records[0]), jsonBytes(t, untouched)) || !bytes.Equal(jsonBytes(t, records[1]), jsonBytes(t, result)) {
		t.Fatal(records)
	}
	raw, e := exportRequests(b.service.Directory, b.service.Now())
	if e != nil {
		t.Fatal(e)
	}
	var exported struct {
		Version  int              `json:"version"`
		Requests []map[string]any `json:"requests"`
	}
	if e = json.Unmarshal(raw, &exported); e != nil {
		t.Fatal(e)
	}
	if exported.Version != 1 || len(exported.Requests) != 2 || !bytes.Equal(jsonBytes(t, exported.Requests[0]), jsonBytes(t, result)) {
		t.Fatal("export lost completion", exported)
	}
}

func TestCompletionRejectsUnauthorizedInvalidAndRegressedClock(t *testing.T) {
	b, code, now := fixture(t)
	id := "11111111-1111-4111-8111-111111111111"
	payload := map[string]any{"requestId": id}
	decode(t, b.request("POST", "/api/requests/complete", payload), 401)
	b.enroll(code)
	decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": id, "text": "preserve"}), 200)
	initial, e := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if e != nil {
		t.Fatal(e)
	}
	old := b.csrf
	b.csrf = "wrong"
	decode(t, b.request("POST", "/api/requests/complete", payload), 403)
	b.csrf = old
	decode(t, b.request("GET", "/api/requests/complete", nil), 400)
	decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": "bad"}), 400)
	decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": "22222222-2222-4222-8222-222222222222"}), 404)
	decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": id, "text": "replacement"}), 400)
	req := httptest.NewRequest("POST", testOrigin+"/api/requests/complete", strings.NewReader(`{"requestId":"`+id+`"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Origin", "https://evil.test")
	req.Header.Set("X-CSRF-Token", b.csrf)
	for _, c := range b.cookies {
		req.AddCookie(c)
	}
	w := httptest.NewRecorder()
	b.service.ServeHTTP(w, req)
	decode(t, w, 403)
	*now = now.Add(-time.Second)
	decode(t, b.request("POST", "/api/requests/complete", payload), 503)
	after, _ := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if !bytes.Equal(initial, after) {
		t.Fatal("rejected completion mutated durable state")
	}
}

func TestCompletionUnknownCommitOutcomeAndRetry(t *testing.T) {
	b, code, now := fixture(t)
	b.enroll(code)
	id := "11111111-1111-4111-8111-111111111111"
	decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": id, "text": "one"}), 200)
	*now = now.Add(time.Hour)
	completedAt := now.UTC().Format(time.RFC3339Nano)
	b.service.afterRename = func() error { return errors.New("directory sync failure") }
	decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": id}), 503)
	b.service = &Service{Directory: b.service.Directory, Now: b.service.Now}
	*now = now.Add(time.Hour)
	got := decode(t, b.request("POST", "/api/requests/complete", map[string]any{"requestId": id}), 200)["request"].(map[string]any)
	if got["completedAt"] != completedAt || got["status"] != "completed" {
		t.Fatal("unknown outcome replay changed receipt", got)
	}
}

func TestCompletionCLIExactIdentityAndReplay(t *testing.T) {
	b, code, now := fixture(t)
	*now = time.Now().UTC().Add(-time.Hour)
	var setupErr error
	code, setupErr = provisionBootstrap(b.service.Directory, *now)
	if setupErr != nil {
		t.Fatal(setupErr)
	}
	b.enroll(code)
	id := "11111111-1111-4111-8111-111111111111"
	text := "unchanged ॐ"
	decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": id, "text": text}), 200)
	exe := filepath.Join(t.TempDir(), "owner")
	cmd := exec.Command("go", "build", "-buildvcs=false", "-o", exe, ".")
	if out, e := cmd.CombinedOutput(); e != nil {
		t.Fatalf("build: %v %s", e, out)
	}
	run := func(id, hash string) ([]byte, error) {
		return exec.Command(exe, "-state", b.service.Directory, "-complete", id, "-expected-text-sha256", hash).CombinedOutput()
	}
	before, _ := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if _, e := run(id, digest("wrong")); e == nil {
		t.Fatal("wrong expected text accepted")
	}
	after, _ := os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("hash mismatch changed state")
	}
	if _, e := run(id, ""); e == nil {
		t.Fatal("empty expected hash accepted")
	}
	if out, e := exec.Command(exe, "-state", b.service.Directory, "-complete", id).CombinedOutput(); e == nil {
		t.Fatalf("missing expected hash accepted: %s", out)
	}
	after, _ = os.ReadFile(filepath.Join(b.service.Directory, "state.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("missing expected hash mutated state")
	}
	first, e := run(id, digest(text))
	if e != nil {
		t.Fatalf("CLI complete: %v %s", e, first)
	}
	var got map[string]any
	if e = json.Unmarshal(first, &got); e != nil {
		t.Fatal(e)
	}
	if got["id"] != id || got["text"] != text || got["status"] != "completed" || got["completedAt"] == nil {
		t.Fatal(got)
	}
	second, e := run(id, digest(text))
	if e != nil || !bytes.Equal(first, second) {
		t.Fatal("CLI replay changed receipt", e, string(second))
	}
	exported, e := exec.Command(exe, "-state", b.service.Directory, "-export").Output()
	if e != nil || !bytes.Contains(exported, []byte(`"status":"completed"`)) {
		t.Fatal("CLI export", e, string(exported))
	}
	if _, e := run("22222222-2222-4222-8222-222222222222", digest(text)); e == nil {
		t.Fatal("missing request completed")
	}
}

func TestCompletionRejectsMalformedPersistedState(t *testing.T) {
	b, code, _ := fixture(t)
	b.enroll(code)
	decode(t, b.request("POST", "/api/requests", map[string]any{"requestId": "11111111-1111-4111-8111-111111111111", "text": "preserve"}), 200)
	path := filepath.Join(b.service.Directory, "state.json")
	original, e := os.ReadFile(path)
	if e != nil {
		t.Fatal(e)
	}
	for _, patch := range []map[string]any{
		{"status": "completed"}, {"status": "completed", "completedAt": "bad"}, {"status": "completed", "completedAt": "2020-01-01T00:00:00Z"}, {"status": "queued", "completedAt": "2026-11-15T12:00:00Z"},
	} {
		var raw map[string]any
		if e = json.Unmarshal(original, &raw); e != nil {
			t.Fatal(e)
		}
		row := raw["requests"].([]any)[0].(map[string]any)
		for k, v := range patch {
			row[k] = v
		}
		if e = os.WriteFile(path, jsonBytes(t, raw), 0600); e != nil {
			t.Fatal(e)
		}
		if _, e = exportRequests(b.service.Directory, b.service.Now()); e == nil {
			t.Fatal("invalid persistent state accepted", patch)
		}
	}
	if e = os.WriteFile(path, original, 0600); e != nil {
		t.Fatal(e)
	}
	if _, e = exportRequests(b.service.Directory, b.service.Now()); e != nil {
		t.Fatal("legacy queued state rejected", e)
	}
}
