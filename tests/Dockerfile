# Verifier image. Runs in its own container: it sees only the paths declared in `artifacts`.
# It compiles the agent's TypeScript and runs it under node, so it needs node and the compiler;
# it scores the result with the standard library, so it needs nothing else. The compiler and the
# node type declarations come from the registry tarballs, pinned by version and checksum, so
# there is no npm and no dependency resolution in this image.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/typescript.tgz https://registry.npmjs.org/typescript/-/typescript-5.6.3.tgz \
    && echo "ef67f8d8ad895858024b7339d3e34bf112cae3c5db1f538c3079038b17ae30fa  /tmp/typescript.tgz" | sha256sum -c - \
    && mkdir -p /usr/local/lib/node_modules/typescript \
    && tar -xzf /tmp/typescript.tgz -C /usr/local/lib/node_modules/typescript --strip-components=1 \
    && ln -s /usr/local/lib/node_modules/typescript/bin/tsc /usr/local/bin/tsc \
    && rm -f /tmp/typescript.tgz

RUN curl -fsSL -o /tmp/types-node.tgz https://registry.npmjs.org/@types/node/-/node-18.19.130.tgz \
    && echo "30e36412dac091a634407127bea2c712c55de136e33c2d234b1529bb876418ca  /tmp/types-node.tgz" | sha256sum -c - \
    && curl -fsSL -o /tmp/undici-types.tgz https://registry.npmjs.org/undici-types/-/undici-types-5.26.5.tgz \
    && echo "503bffdea1bee0526fb2ac75a4ac01ee5e712f251fabdeb8da4b408a519ed465  /tmp/undici-types.tgz" | sha256sum -c - \
    && mkdir -p /usr/local/lib/node_modules/@types/node /usr/local/lib/node_modules/undici-types \
    && tar -xzf /tmp/types-node.tgz -C /usr/local/lib/node_modules/@types/node --strip-components=1 \
    && tar -xzf /tmp/undici-types.tgz -C /usr/local/lib/node_modules/undici-types --strip-components=1 \
    && rm -f /tmp/types-node.tgz /tmp/undici-types.tgz

# Verifier tooling, pinned. Nothing is installed at trial time.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

# test.sh compiles and runs the agent's program, so agent-authored code executes in this image,
# and this image holds the answer keys. That code runs as `runner`, never root.
RUN useradd --create-home --uid 10001 --shell /bin/bash runner

# Artifact landing directories must exist before Harbor uploads the declared artifacts.
RUN mkdir -p /app/screen/src /app/data /app/out

# /app is runner-owned so the build can write its output there, but sticky so runner cannot
# rename or delete the root-owned export beside it.
RUN chown -R runner:runner /app \
    && chmod 1755 /app

# The key for the shipped survey, at a path Harbor does not reserve, readable only by root. /tests
# is a runtime mount, so permissions set on it here are ineffective, and the key cannot be
# protected there.
COPY golden /opt/golden
RUN chmod 700 /opt/golden && chmod 600 /opt/golden/*

# The other survey: its export and its key. test.sh stages the export into a fresh directory after
# the build and runs the agent's program on it a second time, which is what proves the list is
# computed at run time rather than written into the source.
COPY hidden /opt/hidden
RUN chmod -R go-rwx /opt/hidden

COPY . /tests/

WORKDIR /app
