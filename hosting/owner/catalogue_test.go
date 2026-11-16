package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type catalogueTransport func(*http.Request) (*http.Response, error)

func (f catalogueTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestCatalogueAuthBeforeFetchAndSelectedFields(t *testing.T) {
	prior := http.DefaultTransport
	defer func() { http.DefaultTransport = prior }()
	calls := 0
	http.DefaultTransport = catalogueTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.String() != "https://bhakti.eeshan.xyz/data/songs.js" || r.Method != "GET" {
			t.Fatal("unexpected remote target", r.URL)
		}
		deadline, ok := r.Context().Deadline()
		if !ok || time.Until(deadline) > 10*time.Second {
			t.Fatal("missing bounded request deadline")
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`window.BHAKTI_SONGS = [{"slug":"test-song","title":"Śiva","languageTags":["Sanskrit","Hindi"],"subjectTags":["Śiva"],"audioSources":[{"src":"omit"}],"credit":"omit"}];`)), Header: http.Header{}}, nil
	})
	b, code, now := fixture(t)
	decode(t, b.request("GET", "/api/catalogue", nil), 401)
	if calls != 0 {
		t.Fatal("unauthenticated fetch")
	}
	b.enroll(code)
	got := decode(t, b.request("GET", "/api/catalogue?url=https://evil.test", nil), 200)
	if calls != 1 {
		t.Fatal(calls)
	}
	if got["fetchedAt"] != now.UTC().Format(time.RFC3339Nano) {
		t.Fatal(got)
	}
	songs := got["songs"].([]any)
	song := songs[0].(map[string]any)
	if len(songs) != 1 || len(song) != 4 || song["slug"] != "test-song" || song["title"] != "Śiva" || len(song["languageTags"].([]any)) != 2 {
		t.Fatal(got)
	}
	decode(t, b.request("POST", "/api/catalogue", map[string]any{}), 400)
	if calls != 1 {
		t.Fatal("POST fetched")
	}
	*now = now.Add(31 * 24 * time.Hour)
	decode(t, b.request("GET", "/api/catalogue", nil), 401)
	if calls != 1 {
		t.Fatal("expired session fetched")
	}
}
func TestCatalogueRejectsFailuresWithoutEmptySuccess(t *testing.T) {
	prior := http.DefaultTransport
	defer func() { http.DefaultTransport = prior }()
	b, code, _ := fixture(t)
	b.enroll(code)
	for _, tc := range []struct {
		name, body string
		status     int
		failure    error
	}{
		{"transport", "", 0, context.DeadlineExceeded},
		{"upstream status", "[]", 502, nil},
		{"redirect", "", 302, nil},
		{"wrong wrapper", `evil([]);`, 200, nil},
		{"executable suffix", `window.BHAKTI_SONGS = []; alert(1);`, 200, nil},
		{"malformed", `window.BHAKTI_SONGS = [;`, 200, nil},
		{"null", `window.BHAKTI_SONGS = null;`, 200, nil},
		{"invalid row", `window.BHAKTI_SONGS = [{"slug":"../bad","title":"A","languageTags":[],"subjectTags":[]}];`, 200, nil},
		{"duplicate", `window.BHAKTI_SONGS = [{"slug":"a","title":"A","languageTags":[],"subjectTags":[]},{"slug":"a","title":"B","languageTags":[],"subjectTags":[]}];`, 200, nil},
		{"oversize", strings.Repeat(" ", 2*1024*1024+1), 200, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			http.DefaultTransport = catalogueTransport(func(r *http.Request) (*http.Response, error) {
				if tc.failure != nil {
					return nil, tc.failure
				}
				return &http.Response{StatusCode: tc.status, Body: io.NopCloser(strings.NewReader(tc.body)), Header: http.Header{"Location": []string{"https://evil.test/catalogue"}}}, nil
			})
			got := decode(t, b.request("GET", "/api/catalogue", nil), 503)
			if _, exists := got["songs"]; exists {
				t.Fatal("failure disguised as songs", got)
			}
			if !strings.Contains(fmt.Sprint(got["error"]), "unavailable") {
				t.Fatal(got)
			}
		})
	}
}
