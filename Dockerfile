# Use official Python runtime as a parent image
FROM python:3.13-slim-bookworm

ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/kcayut/webclock" \
      org.opencontainers.image.version="${BUILD_VERSION}"

# Set the working directory in the container
WORKDIR /app

# Set timezone (Optional, useful for clock apps)
ENV TZ=Asia/Taipei
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Include only application files; never package installation credentials/state.
COPY app.py sw.js VERSION ./
COPY scripts ./scripts
COPY webclock ./webclock
COPY templates ./templates
COPY static ./static

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run app.py when the container launches
CMD ["python", "app.py"]
