Build the Docker image
----------------------

    docker build . -t solr-cuvs-demo:25.08

Running Solr from the built image
---------------------------------

    docker run -p 8983:8983 solr-cuvs-demo:25.08

Running an example
-------------------

From another terminal, run the following:

    (cd conf && zip -r - *) | curl -X POST --header "Content-Type:application/octet-stream" --data-binary @- "http://localhost:8983/solr/admin/configs?action=UPLOAD&name=cuvs"
    curl "http://localhost:8983/solr/admin/collections?action=CREATE&name=test&numShards=1&collection.configName=cuvs"

    // Now download the dataset, create the batches, upload to Solr
