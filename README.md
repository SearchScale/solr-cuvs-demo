Prerequisites
-------------

Install docker and NVIDIA Container Toolkit.

Build the Docker image
----------------------

    docker build . -t solr-cuvs-demo:25.08

Running Solr from the built image
---------------------------------

    docker run -p 8888:8888 -p 8983:8983 --runtime=nvidia --gpus all solr-cuvs-demo:25.08

Running the example
-------------------

In the browser, open the URL printed (starting with http://127.0.0.1:8888/...). Open the solr-cuvs-demo.ipynb notebook and execute the cells one by one.
Everytime you update the notebook, copy it back to this directory (demo.ipynb) so that those changes persist in subsequent runs.

Troubleshooting
---------------

1. "CUDA driver version is insufficient for CUDA runtime version": This indicates you didn't start the docker container with the `--runtime-nvidia --gpus all`

2. "nvidia-container-cli: requirement error: unsatisfied condition: cuda>=12.9, please update your driver to a newer version, or use an earlier cuda container: unknown." during the start of the `docker run`, might indicate that you have a NVIDIA Driver on your host machine that doesn't support cuda-12.9.
