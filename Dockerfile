FROM rust:1.93-slim AS builder

WORKDIR /app

# Cache dependencies layer
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release
RUN rm src/main.rs

# Build actual source
COPY src ./src
RUN touch src/main.rs && cargo build --release

# Runtime image — minimal
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/target/release/networking-agent /usr/local/bin/networking-agent

# DB lives in a volume
VOLUME ["/data"]

ENV NETWORKING_DB=/data/networking-agent.db

ENTRYPOINT ["networking-agent"]
