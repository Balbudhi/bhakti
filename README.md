# Bhakti

Static devotional-song song page: synchronized lyrics, literal translations, and
word-level meanings. It deploys independently to GitHub Pages at
`bhakti.eeshan.xyz`; the Vedānta Timeline remains a separate site. GitHub's
project URL is deployment infrastructure; the public site URL is the custom
domain.

Public UI follows the maintained [Bhakti design standard](docs/DESIGN_STANDARD.md):
one ground, one ink, established type and control roles, progressive disclosure,
and short directional motion.

On iPhone or iPad, use Safari's **Share → Add to Home Screen**. The manifest
opens Bhakti as a standalone web app. It checks for a newly deployed service
worker when opened or resumed and reloads once only when a new release takes
control; it does not force-refresh every launch or interrupt active audio.

For hosted intake without leaving a laptop awake, use the repository's
`Intake Bhakti Songs` GitHub Actions workflow on `main`. It runs the same
`scripts/bhakti_pipeline.py --publish` path as local intake, commits generated
song pages, uploads high-quality audio to the repository's media release, and
deploys Pages in the same run. Its mode selector defaults to hybrid `economy`:
the audio-dependent transcription, audit, and timing stages remain synchronous
because OpenRouter Batch rejects multimodal input, while the text-only gloss
and translation stages use the same Gemini 3.7 Flash prompts through Batch at
half price. This reduces a typical full-song bill by about 28%, not 50%. Choose
`fast` for fully synchronous completion. OpenRouter permits a text batch to take
up to about 24 hours while a hosted job has a 5.5-hour ceiling, so submit smaller
economy groups rather than one enormous hosted batch.

To run it: open **Actions → Intake Bhakti Songs → Run workflow**, paste one
publicly downloadable HTTPS media link per line (up to 50), choose 1–7 workers,
choose `economy` or `fast`, and run it. URLs supported by `yt-dlp` use the same intake path. The job
is owner-only even if the repository is public; it has no issue/comment,
pull-request, webhook, or public-form trigger. Inputs must resolve only to
public internet addresses, may not contain credentials, and the OpenRouter key
stays in GitHub's encrypted repository secrets. Random visitors therefore
cannot submit songs or spend the API balance.

YouTube currently blocks GitHub-hosted runner IPs with its bot-verification
gate, including the cookie-free embedded client. The workflow fails closed and
does not receive personal YouTube cookies. Public direct media URLs can run
entirely online; YouTube currently needs the local fetch stage before the same
pipeline can continue.

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
silently emulate `--economy`; OpenRouter supplies the text-only half-price
portion of the hybrid economy path.
