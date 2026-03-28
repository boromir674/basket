FROM python:3.12-slim AS base
WORKDIR /app

# Install minimal runtime dependencies for the spike.
RUN pip install --no-cache-dir requests

# Copy pipeline and helper scripts once into the base image.
COPY build_from_euroleague_api.py pipeline_runner.py validate_output.py entrypoint.py season_sync.py regression_tests.py ./
# Include helper scripts and tests in the image so services don't need the full repo mount.
COPY scripts ./scripts
COPY tests ./tests


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
