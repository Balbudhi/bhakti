package main

import (
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

const catalogueURL = "https://bhakti.eeshan.xyz/data/songs.js"
const maxCatalogueBytes = 2 << 20

var catalogueSlug = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)
var errCatalogue = &apiError{503, "The library catalogue is unavailable. Please try again."}

type catalogueSong struct {
	Slug         string   `json:"slug"`
	Title        string   `json:"title"`
	LanguageTags []string `json:"languageTags"`
	SubjectTags  []string `json:"subjectTags"`
}

func parseCatalogue(raw []byte) ([]catalogueSong, error) {
	text := strings.TrimSpace(string(raw))
	const prefix = "window.BHAKTI_SONGS = "
	if !strings.HasPrefix(text, prefix) || !strings.HasSuffix(text, ";") {
		return nil, errCatalogue
	}
	var songs []catalogueSong
	if e := json.Unmarshal([]byte(strings.TrimSuffix(strings.TrimPrefix(text, prefix), ";")), &songs); e != nil || songs == nil {
		return nil, errCatalogue
	}
	seen := map[string]bool{}
	for _, song := range songs {
		if !catalogueSlug.MatchString(song.Slug) || seen[song.Slug] || strings.TrimSpace(song.Title) == "" || song.LanguageTags == nil || song.SubjectTags == nil {
			return nil, errCatalogue
		}
		for _, tags := range [][]string{song.LanguageTags, song.SubjectTags} {
			for _, tag := range tags {
				if strings.TrimSpace(tag) == "" {
					return nil, errCatalogue
				}
			}
		}
		seen[song.Slug] = true
	}
	return songs, nil
}

func (s *Service) catalogue(w http.ResponseWriter, r *http.Request) error {
	if r.Method != "GET" {
		return errInvalid
	}
	token := cookieValue(r, sessionCookie)
	if token == "" {
		return errUnauthorized
	}
	// Authenticate under the state lock, then release it before bounded network I/O.
	if e := transact(s.Directory, s.now(), s.afterRename, func(st *state, _ func() error) error {
		if _, ok := st.Sessions[digest(token)]; !ok {
			return errUnauthorized
		}
		return nil
	}); e != nil {
		return e
	}
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, e := http.NewRequestWithContext(r.Context(), "GET", catalogueURL, nil)
	if e != nil {
		return errCatalogue
	}
	response, e := client.Do(req)
	if e != nil {
		return errCatalogue
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return errCatalogue
	}
	raw, e := io.ReadAll(io.LimitReader(response.Body, maxCatalogueBytes+1))
	if e != nil || len(raw) > maxCatalogueBytes {
		return errCatalogue
	}
	songs, e := parseCatalogue(raw)
	if e != nil {
		return e
	}
	jsonResponse(w, http.StatusOK, map[string]any{"songs": songs, "fetchedAt": s.now().UTC().Format(time.RFC3339Nano)})
	return nil
}
