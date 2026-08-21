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
