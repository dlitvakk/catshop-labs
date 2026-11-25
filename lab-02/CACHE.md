# Cache measurements

Same commit (`b0f0fdc`), same workflow (`publish-lab-02.yml`), run twice: once cold, once warm.

| | cold | warm |
|---|---|---|
| `test` job | 22s | 12s |
| `publish` job | 33s | 23s |
| Docker build step | 16s, 0% cached | 5s, 47% cached |
| test + publish | 55s | 35s |

The Docker layer cache cut the image build from 16s to 5s, and the pip cache cut the `test` job from 22s to 12s because dependencies were restored instead of downloaded.

What is cached:

- pip: `actions/cache` on `~/.cache/pip`, keyed on `hashFiles(requirements.txt, requirements-dev.txt)`, so it refreshes whenever a dependency changes.
- Docker layers: buildx `type=gha,mode=max`, keyed by BuildKit on layer content.
