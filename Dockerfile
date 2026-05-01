FROM python:3.12-slim AS base
WORKDIR /app

# TODO: stop code-gen and use proper uv+pyproject+multi-stage dockerfile as toolchain for python-backed operations


# Allow importing the shared library under /app/src (e.g. `from basket.elo import ...`).
ENV PYTHONPATH=/app/src

# Install minimal runtime dependencies for the spike.
RUN pip install --no-cache-dir requests attrs pyyaml

# Copy pipeline and helper scripts once into the base image.
COPY build_from_euroleague_api.py pipeline_runner.py validate_output.py entrypoint.py season_sync.py season_ops.py regression_tests.py elo.py build_score_timeline.py style_insights.py ./

# Shared library code (single source of truth for Elo computations).
COPY src ./src
# Include helper scripts and tests in the image so services don't need the full repo mount.
COPY scripts ./scripts


# Dedicated test stage: extend base and add pytest only here.
FROM base AS tests
RUN pip install --no-cache-dir pytest


# Runtime/validator image used by the main services.
FROM base AS validator
WORKDIR /app

# Default: expose a single convenient command that runs the pipeline
# (single or multi-game) and then validates the produced JSON.
ENTRYPOINT ["python", "entrypoint.py"]
CMD ["run_pipeline_and_validate"]
