# docker build -f deploy/docker/Dockerfile -t hgjazhgj/alas:latest .
# docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm hgjazhgj/alas

FROM python:3.14.6-slim

WORKDIR /app/AzurLaneAutoScript

COPY pyproject.toml .python-version ./

# Initial download of UiAutomator2 is slow outside of China using appetizer mirror, switch to GitHub
RUN apt update \
 && apt install -y git adb libgomp1 openssh-client \
 && apt install -y build-essential pkg-config \
 && apt install -y libavformat-dev libavcodec-dev libavdevice-dev \
 && apt install -y libavutil-dev libswscale-dev libswresample-dev libavfilter-dev \
 && git config --global --add safe.directory '*' \
 && pip install uv \
 && uv sync --python 3.14.6 \
 && rm -rf ~/.cache/pip ~/.cache/uv

CMD uv run python gui.py
