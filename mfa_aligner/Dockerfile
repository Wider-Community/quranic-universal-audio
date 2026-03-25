FROM condaforge/mambaforge:latest

# System deps (DEBIAN_FRONTEND prevents tzdata interactive prompt)
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Create MFA conda environment with pinned Python 3.11
# (Python 3.14 breaks MFA due to Path.copy() conflict)
RUN mamba create -p /env -c conda-forge python=3.11 montreal-forced-aligner -y && \
    mamba clean --all -y

# Install Python deps into the MFA env
RUN /env/bin/pip install --no-cache-dir gradio soundfile tgt numpy PyYAML \
    "quranic-phonemizer>=2.0"

# Create non-root user (HF Spaces requirement)
RUN useradd -m -u 1000 user
ENV HOME=/home/user
ENV MFA_ROOT_DIR=/home/user/mfa_data

# Init MFA server as non-root user
USER user
RUN conda run -p /env mfa server init

# Copy app files
WORKDIR /home/user/app
COPY --chown=user:user . /home/user/app

EXPOSE 7860

CMD ["conda", "run", "-p", "/env", "--no-capture-output", "python", "app.py"]
