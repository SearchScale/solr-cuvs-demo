import numpy as np
from tqdm import tqdm
import pandas as pd
import json
import gzip
import time
import re
import requests
from functools import wraps
import importlib
import warnings

def time_it(func: any):
    """returns result and elapsed time"""
    @wraps(func)
    def inner(*args, **kwargs):
        pref = time.perf_counter()
        result = func(*args, **kwargs)
        delta = time.perf_counter() - pref
        return result, delta
    return(inner)

@time_it
def run_single_query(solr_url, query_prefix, vector_str, return_limit=10):
    """
    Function for submitting individual queries to Solr.
    """
    
    query_obj = {
      "query": {
        "lucene": {
          "df": "name",
          "query": query_prefix + vector_str
        }
      },
      "fields": "id",
      "limit": return_limit
    }

    response = requests.post(solr_url, json = query_obj)

    # Convert response text to dict:
    response = json.loads(response.text)

    # Initialize outputs
    out = {}

    # Validate responses
    if response['responseHeader']['status'] == 0:
        out['QTime'] = response['responseHeader']['QTime']
    else:
        print(response)
        raise ValueError('Query did not complete successfully.')

    # Accumulate doc_ids
    out['doc_ids'] = [d['id'] for d in response['response']['docs']]
    return(out)

def run_all_queries(solr_url, query_prefix, query_vector_strs, num_queries, batch_size=1):
    print(f'batch_size={batch_size}')
    start_time = time.perf_counter()
    query_results = [run_single_query(solr_url, query_prefix, vector_str) for vector_str in tqdm(query_vector_strs, desc='Run progress')]
    elapsed_time = time.perf_counter() - start_time

    # Store matches
    topK_ids = [r[0] for r in query_results]
    topK_ids = [[int(ii) for ii in topK_ids[jj]['doc_ids']] for jj in range(len(query_results))]
    
    # Assemble run times
    timing_store = [r[1] for r in query_results]
    run_times = pd.Series(timing_store)
    P99 = run_times.quantile(.99)
    
    print('Wall time:', f'{elapsed_time:.2f} s')
    print(f'QPS={num_queries/elapsed_time:.2f}, P99={P99*1000:0.2f} ms')
    print()
    return(topK_ids)
    
def generate_config_xml(model_name, dim=2048, output_dir='./tmp_config', **kwargs):
    """
    Dynamically generate schema.xml and solrconfig.xml for various indexing algorithms.

    model_name: str
      Select model_name of 'hnsw' or 'cuvs'.

    params: dict(str)
      Specify relevant set of parameters for the model_name selected.

    dim: int
      Number of dimensions in vector.
    """
    print(f'Generating {model_name} schema.xml and solrconfig.xml files.')
    
    if model_name == 'hnsw':
        hnswMaxConnections = kwargs['hnswMaxConnections']
        hnswBeamWidth = kwargs['hnswBeamWidth']
        
        # Build params: hnswBeamWidth=efConstruction, hnswMaxConnections=M.
        # No efSearch parameter available.
        
        schema_xml = f'''<?xml version="1.0" ?>
<!--
 Licensed to the Apache Software Foundation (ASF) under one or more
 contributor license agreements.  See the NOTICE file distributed with
 this work for additional information regarding copyright ownership.
 The ASF licenses this file to You under the Apache License, Version 2.0
 (the "License"); you may not use this file except in compliance with
 the License.  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
-->

<!-- Test schema file for DenseVectorField -->

<schema name="schema-densevector" version="1.7">

    <fieldType name="string" class="solr.StrField" multiValued="true"/>
    <fieldType name="knn_vector" class="solr.DenseVectorField" vectorDimension="{dim}" knnAlgorithm="hnsw" hnswMaxConnections="{hnswMaxConnections}" hnswBeamWidth="{hnswBeamWidth}" similarityFunction="cosine" />
    <fieldType name="plong" class="solr.LongPointField" useDocValuesAsStored="false"/>

    <field name="id" type="string" indexed="true" stored="true" multiValued="false" required="false"/>
    <field name="title" type="string" indexed="true" stored="true" multiValued="false" required="false"/>
    <field name="article_vector" type="knn_vector" indexed="true" stored="true"/>
    <field name="article" type="string" indexed="true" stored="true"/>

    <field name="_version_" type="plong" indexed="true" stored="true" multiValued="false" />
    <uniqueKey>id</uniqueKey>
</schema>
        '''

        # No params modified in solrconfig.xml for hnsw.
        solrconfig_xml = '''<?xml version="1.0" ?>
<!--
  This software was produced for the U. S. Government
  under Contract No. W15P7T-11-C-F600, and is
  subject to the Rights in Noncommercial Computer Software
  and Noncommercial Computer Software Documentation
  Clause 252.227-7014 (JUN 1995)

  Copyright 2013 The MITRE Corporation. All Rights Reserved.

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
  -->

<!-- a basic solrconfig that tests can use when they want simple minimal solrconfig/schema
     DO NOT ADD THINGS TO THIS CONFIG! -->
<config>
    <luceneMatchVersion>${tests.luceneMatchVersion:LATEST}</luceneMatchVersion>
    <dataDir>${solr.data.dir:}</dataDir>
    <directoryFactory name="DirectoryFactory" class="${solr.directoryFactory:solr.NRTCachingDirectoryFactory}"/>

    <!-- for postingsFormat="..." -->

    <!-- since Solr 4.8: -->
    <requestHandler name="/select" class="solr.SearchHandler"></requestHandler>

</config>
        '''
        
    elif model_name == 'cuvs':
        cuvsWriterThreads = kwargs['cuvsWriterThreads']
        graphDegree = kwargs['graphDegree']
        intGraphDegree = kwargs['intGraphDegree']

        schema_xml = f'''<?xml version="1.0" ?>
<!--
 Licensed to the Apache Software Foundation (ASF) under one or more
 contributor license agreements.  See the NOTICE file distributed with
 this work for additional information regarding copyright ownership.
 The ASF licenses this file to You under the Apache License, Version 2.0
 (the "License"); you may not use this file except in compliance with
 the License.  You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
-->

<!-- Test schema file for DenseVectorField -->

<schema name="schema-densevector" version="1.7">

    <fieldType name="string" class="solr.StrField" multiValued="true"/>
    <fieldType name="knn_vector" class="solr.DenseVectorField" vectorDimension="{dim}" knnAlgorithm="cuvs" similarityFunction="cosine" />
    <fieldType name="plong" class="solr.LongPointField" useDocValuesAsStored="false"/>

    <field name="id" type="string" indexed="true" stored="true" multiValued="false" required="false"/>
    <field name="title" type="string" indexed="true" stored="true" multiValued="false" required="false"/>
    <field name="article_vector" type="knn_vector" indexed="true" stored="true"/>
    <field name="article" type="string" indexed="true" stored="true"/>

    <field name="_version_" type="plong" indexed="true" stored="true" multiValued="false" />
    <uniqueKey>id</uniqueKey>
</schema>
        '''

        solrconfig_xml = f'''<?xml version="1.0" ?>
<!--
  This software was produced for the U. S. Government
  under Contract No. W15P7T-11-C-F600, and is
  subject to the Rights in Noncommercial Computer Software
  and Noncommercial Computer Software Documentation
  Clause 252.227-7014 (JUN 1995)

  Copyright 2013 The MITRE Corporation. All Rights Reserved.

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
  -->

<!-- a basic solrconfig that tests can use when they want simple minimal solrconfig/schema
     DO NOT ADD THINGS TO THIS CONFIG! -->
<config>
    <luceneMatchVersion>${{tests.luceneMatchVersion:LATEST}}</luceneMatchVersion>
    <dataDir>${{solr.data.dir:}}</dataDir>
    <directoryFactory name="DirectoryFactory" class="${{solr.directoryFactory:solr.NRTCachingDirectoryFactory}}"/>

    <!-- for postingsFormat="..." -->
    <codecFactory name="CodecFactory" class="org.apache.solr.core.CuvsCodecFactory">
        <int name="cuvsWriterThreads">{cuvsWriterThreads}</int> 
        <int name="graphDegree">{graphDegree}</int> 
        <int name="intGraphDegree">{intGraphDegree}</int> 
    </codecFactory>

    <!-- since Solr 4.8: -->
    <queryParser name="cuvs" class="org.apache.solr.search.neural.CuvsQParserPlugin"/>
    <requestHandler name="/select" class="solr.SearchHandler"></requestHandler>

</config>
        '''
        
    else:
        raise ValueError('Unknown model value. Choose "hnsw" or "cuvs".')
        
    # Write files to disk
    with open(output_dir + '/schema.xml', 'w') as file:
        file.write(schema_xml)

    with open(output_dir + '/solrconfig.xml', 'w') as file:
        file.write(solrconfig_xml)

    print('Completed writing all XML files.')
    return()

def generate_solr_bash_scripts(data_dir, model_name='hnsw', jvm_mem='4G'):
    """
    Function for generating bash scritps to launch Solr, upload data, and start indexing.

    data_dir: str
      Directory with javabin formated vector data.

    model_name: str
      Select indexing algorithm. Choose from 'hnsw' or 'cuvs'.

    jvm_mem: str
      Heap memory allocation for Java. Default is '4G' for 4GB.
    """
    if model_name not in ('hnsw', 'cuvs'):
        raise ValueError(f"Invalid model_name: {model_name}. Value must be 'hnsw' or 'cuvs'.")
    
    start_solr_mod_sh = f'''#!/bin/bash
# Select hardware accelerator (cpu or gpu)
export model_name={model_name}
export jvm_mem={jvm_mem}
export LD_LIBRARY_PATH=/cuvs/cpp/build:$LD_LIBRARY_PATH

# Stop Solr if running
pkill -9 java # kill all java processes
rm -rf solr-10.0.0-SNAPSHOT
wait 30

# Start a Solr instance
tar -xf solr-10.0.0-SNAPSHOT.tgz
cd solr-10.0.0-SNAPSHOT
bin/solr start -m $jvm_mem --force

# ./tmp_config dir contains dynamically generated Solr config xml files
(cd ../tmp_config && zip -r - *) | curl -X POST --header "Content-Type:application/octet-stream" --data-binary @- "http://localhost:8983/solr/admin/configs?action=UPLOAD&name=$model_name"
curl "http://localhost:8983/solr/admin/collections?action=CREATE&name=test&numShards=1&collection.configName=$model_name"
    '''
    
    # Removed internal timing function from upload_all_files_mod.sh script
    upload_files_mod_sh = f'''#!/bin/bash
    
# Define the URL endpoint
URL="http://localhost:8983/solr/test/update?commit=true&overwrite=false"

# Define the directory containing files to upload

DIRECTORY="{data_dir}"
# install httpie
# Loop through each file in the directory and post it in the background
for FILE in "$DIRECTORY"/*; do
    if [ -f "$FILE" ]; then  # Check if it's a file
        echo "Uploading $FILE..."
        http --ignore-stdin POST "$URL" Content-Type:application/javabin @"$FILE" &
    fi
done

wait

# Wait for all background processes to finish
echo "All files in the directory uploaded."
    '''
    
    # Write files to disk
    with open('./start_solr_mod.sh', 'w') as file:
        file.write(start_solr_mod_sh)
    
    with open('./upload_all_files_mod.sh', 'w') as file:
        file.write(upload_files_mod_sh)

    print('Sucessfully written ./start_solr_mod.sh and ./upload_all_files_mod.sh.')
    return()

def upload_and_index_file(file_name, solr_url='http://localhost:8983/solr/test'):
    """
    Upload and index javabin file with Solr URL request.

    file_name: str
      Javabin file to upload, including the relative path. Example: './batches_10k/wiki.0'.

    solr_url: str
      Solr URL with name of collection included. Default value: 'http://localhost:8983/solr/test'.
    """
    
    url_request = solr_url + '/update?commit=true&overwrite=false'

    print(f'Processing {file_name}.')
    
    with open(file_name, 'rb') as f:
        headers = {'Content-Type': 'application/javabin'}
        response = requests.post(url_request, headers=headers, data=f)
        status_code = response.status_code
        
        if status_code == 200:
            # Success response
            content = json.loads(response.content.decode('utf-8'))
            QTime = content['responseHeader']['QTime']
            print(f'Successfully uploaded and indexed {file_name} in {QTime} ms.')
        else:
            content = json.loads(response.content.decode('utf-8'))
            print(content)
            raise ValueError(f'FAILED to process {file_name}. Response status code {status_code} is not equal to 200.')

    return(status_code)

def load_javabin_data(data_file, row_limit=-1, jar_classpath='./solr-cuvs-benchmarks-1.0-SNAPSHOT-jar-with-dependencies.jar'):
    """
    Load data from javabin files.

    data_file: str
      Input data file name.

    row_limit: int
      Limit on how many results are returned. Default value of -1 for no limit.

    jar_classpath: str
      Jar file with cuVS for Solr plugin (default='./solr-cuvs-benchmarks-1.0-SNAPSHOT-jar-with-dependencies.jar').
    """
    
    # Read vectors from javabin file
    import jpype
    import jpype.imports
    
    # Start the JVM, adjust classpath to include the relevant Java libraries
    try:
        jpype.startJVM(classpath=[jar_classpath])
    except:
        print('Skiping startJVM. JVM already running.')
    
    # Load JavaBinCodec from jar
    from org.apache.solr.common.util import JavaBinCodec
        
    # Use JavaBinCodec to read the file.
    codec = JavaBinCodec()
    with open(data_file, 'rb') as f:
        java_input_stream = jpype.JClass('java.io.ByteArrayInputStream')(f.read())
        obj = codec.unmarshal(java_input_stream)

    if row_limit > 0:
        obj = obj[:row_limit]
    
    # Separate ids and article vectors:
    ids = [int(str(obj[ii]['id'])) for ii in range(len(obj))]
    ids = np.array(ids)
    
    # Extract vectors
    vectors = [np.array(obj[ii]['article_vector'].toArray()) for ii in range(len(obj))]
    return(ids, vectors)

def calc_recall(found_indices, ground_truth):
    found_indices = xp.asarray(found_indices)
    bs, k = found_indices.shape
    if bs != ground_truth.shape[0]:
        raise RuntimeError(
            "Batch sizes do not match {} vs {}".format(
                bs, ground_truth.shape[0]
            )
        )
    if k > ground_truth.shape[1]:
        raise RuntimeError(
            "Not enough indices in the ground truth ({} > {})".format(
                k, ground_truth.shape[1]
            )
        )
    n = 0
    # Go over the batch
    for i in range(bs):
        # Note, ivf-pq does not guarantee the ordered input, hence the use of intersect1d
        n += xp.intersect1d(found_indices[i, :k], ground_truth[i, :k]).size
        # To-do: Change to account for equidistant indices that are not captured.
    
    #recall = n / found_indices.size
    recall = n / (bs * ground_truth.shape[1])
    return recall

def import_with_fallback(primary_lib, secondary_lib=None, alias=None):
    """
    Attempt to import a primary library, with an optional fallback to a
    secondary library.
    Optionally assigns the imported module to a global alias.

    Parameters
    ----------
    primary_lib : str
        Name of the primary library to import.
    secondary_lib : str, optional
        Name of the secondary library to use as a fallback. If `None`,
        no fallback is attempted.
    alias : str, optional
        Alias to assign the imported module globally.

    Returns
    -------
    module or None
        The imported module if successful; otherwise, `None`.

    Examples
    --------
    >>> xp = import_with_fallback('cupy', 'numpy')
    >>> mod = import_with_fallback('nonexistent_lib')
    >>> if mod is None:
    ...     print("Library not found.")
    """
    try:
        module = importlib.import_module(primary_lib)
    except ImportError:
        if secondary_lib is not None:
            try:
                module = importlib.import_module(secondary_lib)
            except ImportError:
                module = None
        else:
            module = None
    if alias and module is not None:
        globals()[alias] = module
    return module

rmm = import_with_fallback("rmm")
gpu_system = False

def force_fallback_to_numpy():
    global xp, gpu_system
    xp = import_with_fallback("numpy")
    gpu_system = False
    warnings.warn(
        "Consider using a GPU-based system to greatly accelerate "
        " generating groundtruths using cuVS."
    )

if rmm is not None:
    gpu_system = True
    try:
        import cuvs
        import pylibraft
        from pylibraft.common import DeviceResources
        from rmm.allocators.cupy import rmm_cupy_allocator

        from cuvs.neighbors.brute_force import build, search

        xp = import_with_fallback("cupy", "numpy")
    except ImportError:
        # RMM is available, cupy is available, but cuVS is not
        force_fallback_to_numpy()
else:
    # No RMM, no cuVS, but cupy is available
    force_fallback_to_numpy()

def cpu_search(dataset, queries, k, metric="squeclidean"):
    """
    Find the k nearest neighbors for each query point in the dataset using the
    specified metric.

    Parameters
    ----------
    dataset : numpy.ndarray
        An array of shape (n_samples, n_features) representing the dataset.
    queries : numpy.ndarray
        An array of shape (n_queries, n_features) representing the query
        points.
    k : int
        The number of nearest neighbors to find.
    metric : str, optional
        The distance metric to use. Can be 'squeclidean' or 'inner_product'.
        Default is 'squeclidean'.

    Returns
    -------
    distances : numpy.ndarray
        An array of shape (n_queries, k) containing the distances
        (for 'squeclidean') or similarities
        (for 'inner_product') to the k nearest neighbors for each query.
    indices : numpy.ndarray
        An array of shape (n_queries, k) containing the indices of the
        k nearest neighbors in the dataset for each query.

    """
    if metric == "squeclidean":
        diff = queries[:, xp.newaxis, :] - dataset[xp.newaxis, :, :]
        dist_sq = xp.sum(diff**2, axis=2)  # Shape: (n_queries, n_samples)

        indices = xp.argpartition(dist_sq, kth=k - 1, axis=1)[:, :k]
        distances = xp.take_along_axis(dist_sq, indices, axis=1)

        sorted_idx = xp.argsort(distances, axis=1)
        distances = xp.take_along_axis(distances, sorted_idx, axis=1)
        indices = xp.take_along_axis(indices, sorted_idx, axis=1)

    elif metric == "inner_product":
        similarities = xp.dot(
            queries, dataset.T
        )  # Shape: (n_queries, n_samples)

        neg_similarities = -similarities
        indices = xp.argpartition(neg_similarities, kth=k - 1, axis=1)[:, :k]
        distances = xp.take_along_axis(similarities, indices, axis=1)

        sorted_idx = xp.argsort(-distances, axis=1)

    else:
        raise ValueError(
            "Unsupported metric in cuvs-bench-cpu. "
            "Use 'squeclidean' or 'inner_product' or use the GPU package"
            "to use any distance supported by cuVS."
        )

    distances = xp.take_along_axis(distances, sorted_idx, axis=1)
    indices = xp.take_along_axis(indices, sorted_idx, axis=1)

    return distances, indices


def calc_truth(dataset, queries, k, metric="sqeuclidean", filter=None):
    """
    Calculate ground truth nearest neighbors with optional filtering.
    
    Parameters:
    -----------
    dataset : array-like
        Reference vectors
    queries : array-like
        Query vectors
    k : int
        Number of nearest neighbors to find
    metric : str
        Distance metric to use
    filter : object, optional
        Filter object to apply during search
    
    Returns:
    --------
    tuple: (distances, indices)
    """
    queries = xp.asarray(queries, dtype=xp.float32)
    dataset = xp.asarray(dataset, dtype=xp.float32)
    
    print("Building index for full dataset ({} vectors)...".format(dataset.shape[0]))
    
    if gpu_system:
        resources = DeviceResources()
        
        try:
            # Build index with full dataset
            index = build(dataset, metric=metric)
            
            # Search with optional filter
            print("Searching with full dataset...")
            if filter is not None:
                D, Ind = search(index, queries, k, prefilter=filter)
            else:
                D, Ind = search(index, queries, k)
                
            resources.sync()
            
            # Convert results back to CPU before returning
            distances = xp.asnumpy(D)
            indices = xp.asnumpy(Ind)
            
        finally:
            # Clean up GPU memory
            if 'index' in locals():
                del index
            del dataset, queries
            mem_pool = xp.get_default_memory_pool()
            mem_pool.free_all_blocks()
            
    else:
        # CPU search doesn't support filters
        if filter is not None:
            print("Warning: Filters not supported in CPU implementation")
        distances, indices = cpu_search(dataset, queries, k, metric=metric)

    return distances, indices