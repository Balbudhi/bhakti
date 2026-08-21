# Bhakti

Static devotional-song reader: synchronized lyrics, literal translations, and
word-level meanings. It deploys independently to GitHub Pages at
`bhakti.eeshan.xyz`; the Vedānta Timeline remains a separate site. GitHub's
project URL is deployment infrastructure; the public site URL is the custom
domain.

For hosted intake without leaving a laptop awake, use the repository's
`Intake Bhakti Songs` GitHub Actions workflow on `main`. It runs the same
`scripts/bhakti_pipeline.py --publish` path as local intake, commits generated
readers, and deploys Pages in the same run. It is for normal synchronous jobs;
the half-price `--economy` Batch API mode remains a separate path because
OpenRouter batches can take up to about 24 hours while GitHub-hosted jobs are
limited to 6 hours.

To run it: open **Actions → Intake Bhakti Songs → Run workflow**, paste one
publicly downloadable HTTPS media link per line (up to 50), choose 1–7 workers,
and run it. YouTube, YouTube Music, and other URLs supported by `yt-dlp` use the
same intake path. The job
is owner-only even if the repository is public; it has no issue/comment,
pull-request, webhook, or public-form trigger. Inputs must resolve only to
public internet addresses, may not contain credentials, and the OpenRouter key
stays in GitHub's encrypted repository secrets. Random visitors therefore
cannot submit songs or spend the API balance.

The production client supports two explicit providers with the same prompts,
audio payloads, structured schemas, retries, and publication gates:

- `BHAKTI_GEMINI_PROVIDER=openrouter` uses the shared Dev OpenRouter key and is
  the default.
- `BHAKTI_GEMINI_PROVIDER=google` uses the direct Gemini OpenAI-compatible API
  with `GEMINI_API_KEY` or a private `~/Dev/gemini.key` file.

The August 21, 2026 live probe found that the current `bhakti` Google project is
without available quota, so Google rejects inference with a
permanent `429`. Hosted intake is therefore pinned to OpenRouter. Direct mode
remains available for a future funded or Free Tier project, but it does not
silently emulate `--economy`; OpenRouter is the supported Batch API path.
