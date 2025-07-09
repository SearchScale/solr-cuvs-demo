FROM nvidia/cuda:12.9.1-devel-ubuntu24.04

# Install git and other dependencies that might be needed for the build
RUN apt-get update && apt-get install -y \
    git build-essential wget ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Install cmake 3.30 and add it to the PATH
RUN wget https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8-linux-x86_64.tar.gz \
    && tar -xzf cmake-3.31.8-linux-x86_64.tar.gz -C /opt \
    && rm cmake-3.31.8-linux-x86_64.tar.gz
ENV PATH="/opt/cmake-3.31.8-linux-x86_64/bin:${PATH}"

# Clone the repository
RUN apt install libnccl-dev -y
RUN apt update 
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata
RUN apt install python3 -y

RUN git clone https://github.com/searchscale/cuvs
WORKDIR /cuvs
RUN git checkout investigate-multithreaded-failures
RUN ./build.sh libcuvs

# Install JDK 22
RUN wget https://corretto.aws/downloads/resources/22.0.2.9.1/java-22-amazon-corretto-jdk_22.0.2.9-1_amd64.deb
RUN apt install java-common
RUN dpkg -i java-22-amazon-corretto-jdk_22.0.2.9-1_amd64.deb
RUN java -version

# Build cuvs-java
RUN apt install -y maven
WORKDIR /cuvs/java
RUN ./build.sh

# Build Lucene
WORKDIR /
RUN git clone https://github.com/searchscale/lucene
WORKDIR /lucene
RUN git checkout cuvs-integration-10x-24.08
COPY lucene-local-maven.patch /lucene/lucene-local-maven.patch
RUN git apply lucene-local-maven.patch
RUN git status
RUN ./gradlew eclipse :writeLocks mavenToLocal

# Build Solr
WORKDIR /
RUN git clone https://github.com/searchscale/solr
WORKDIR /solr
RUN git checkout ishan/cuvs-integration-2408
COPY solr-local-maven.patch /solr/solr-local-maven.patch
RUN git apply solr-local-maven.patch
RUN git status
RUN ./gradlew --write-locks updateLicenses validateJarChecksums dev distTar

# Run Solr
WORKDIR /
RUN mkdir workingarea
WORKDIR /workingarea
RUN cp /solr/solr/packaging/build/distributions/solr-10.0.0-SNAPSHOT.tgz .
RUN tar -xf solr-10.0.0-SNAPSHOT.tgz
WORKDIR /workingarea/solr-10.0.0-SNAPSHOT
RUN echo "SOLR_JETTY_HOST=0.0.0.0" >> bin/solr.in.sh

EXPOSE 8983

CMD ["bin/solr", "start", "-m", "16G", "--force", "-f"]
