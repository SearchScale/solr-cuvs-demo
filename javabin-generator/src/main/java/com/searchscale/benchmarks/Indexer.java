package com.searchscale.benchmarks;

import static org.apache.solr.common.util.JavaBinCodec.END;
import static org.apache.solr.common.util.JavaBinCodec.ITERATOR;

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.GZIPInputStream;

import org.apache.solr.common.MapWriter;
import org.apache.solr.common.util.JavaBinCodec;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

public class Indexer {

  public static Map<String, String> parseStringToMap(String[] pairs) {
    Map<String, String> map = new HashMap<>();

    // Split the input string by commas to get individual key-value pairs

    for (String pair : pairs) {
      // Split each pair by '=' to separate key and value
      String[] keyValue = pair.split("=");

      // Check if the split resulted in exactly two parts
      if (keyValue.length == 2) {
        String key = keyValue[0].trim(); // Remove any potential whitespace
        String value = keyValue[1].trim();
        map.put(key, value);
      } else {
        // Log or handle malformed key-value pairs
        System.err.println("Malformed key-value pair: " + pair);
      }
    }

    return map;
  }

  public static class Params {

    public final int threads;

    public final String solrUrl;
    public final String dataFile;
    public final String queryFile;
    public final String testColl;
    public final int batchSize;
    public final int queryCount;
    public final boolean runQuery;
    public final String outputFile;

    public final int docsCount;
    public final boolean isLegacy;

    Map<String, String> p;

    public Params(String[] s) {
      p = parseStringToMap(s);
      threads = Integer.parseInt(p.getOrDefault("index_threads", "1"));
      solrUrl = p.getOrDefault("solr_url", "http://localhost:8983/solr");
      dataFile = p.get("data_file");
      testColl = p.getOrDefault("test_coll", "test");
      batchSize = Integer.parseInt(p.getOrDefault("batch_size", "1000"));
      docsCount = Integer.parseInt(p.getOrDefault("docs_count", "10000"));
      queryFile = p.get("query_file");
      outputFile = p.get("output_file");

      queryCount = Integer.parseInt(p.getOrDefault("query_count", "1"));
      runQuery = Boolean.parseBoolean(p.getOrDefault("query", "false"));
      isLegacy = Boolean.parseBoolean(p.getOrDefault("legacy", "false"));
    }

  }

  static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

  static final String EOL = "###";

  public static void main(String[] args) throws Exception {
    Params p = new Params(args);
    long docsCount = p.docsCount;
    long batchSz = p.batchSize;
    System.out.println(p.p.toString());
    if (batchSz > docsCount)
      batchSz = docsCount;

    // Check if the file is fvec/fbin format
    if (p.dataFile.endsWith(".fvecs") || p.dataFile.endsWith(".fbin") || p.dataFile.endsWith(".fvecs.gz")) {
      processFvecFile(p, docsCount, batchSz);
    } else {
      // Original CSV processing
      try (InputStream in = new GZIPInputStream(new FileInputStream(p.dataFile))) {
        BufferedReader br = new BufferedReader(new InputStreamReader(in));
        String header = br.readLine();
        int count = 0;
        for (int i = 0;; i++) {
          String name = p.outputFile + "." + i;
          try (FileOutputStream os = new FileOutputStream(name)) {
            JavaBinCodec codec = new J(os);
            if (!writeBatch(batchSz, br, codec, p.isLegacy))
              break;
            System.out.println(name);
            count += batchSz;
            if (count > docsCount)
              break;
          }
        }
      }
    }
  }

  private static void processFvecFile(Params p, long docsCount, long batchSz) throws Exception {
    List<float[]> vectors = new ArrayList<>();
    
    // Read all vectors from the fvec file
    FBIvecsReader.readFvecs(p.dataFile, (int) docsCount, vectors);
    
    int totalProcessed = 0;
    int batchIndex = 0;
    
    while (totalProcessed < vectors.size() && totalProcessed < docsCount) {
      String name = p.outputFile + "." + batchIndex;
      try (FileOutputStream os = new FileOutputStream(name)) {
        JavaBinCodec codec = new J(os);
        int batchCount = 0;
        
        codec.writeTag(ITERATOR);
        
        while (batchCount < batchSz && totalProcessed < vectors.size() && totalProcessed < docsCount) {
          float[] vector = vectors.get(totalProcessed);
          
          // Create a document with id and vector
          final int docId = totalProcessed;
          final float[] vectorData = vector;
          MapWriter d = ew -> {
            ew.put("id", String.valueOf(docId));
            if (p.isLegacy) {
              // Convert float[] to List<Float> for legacy mode
              List<Float> floatList = new ArrayList<>();
              for (float f : vectorData) {
                floatList.add(f);
              }
              ew.put("article_vector", floatList);
            } else {
              ew.put("article_vector", vectorData);
            }
          };
          
          codec.writeMap(d);
          batchCount++;
          totalProcessed++;
        }
        
        codec.writeTag(END);
        codec.close();
        System.out.println(name);
        batchIndex++;
      }
    }
  }

  private static boolean writeBatch(long docsCount, BufferedReader br, JavaBinCodec codec, boolean legacy)
      throws IOException {
    codec.writeTag(ITERATOR);
    int count = 0;
    for (;;) {
      String line = br.readLine();
      if (line == null) {
        System.out.println(EOL);
        return false;
      }
      MapWriter d = null;
      try {
        d = parseRow(parseLine(line), legacy);
        codec.writeMap(d);

        count++;
        if (count >= docsCount)
          break;
      } catch (Exception e) {
        // invalid doc
        continue;
      }

    }
    codec.writeTag(END);
    codec.close();
    return true;
  }

  static class J extends JavaBinCodec {
    public J(OutputStream os) throws IOException {
      super(os, null);
    }

    @Override
    public void writeVal(Object o) throws IOException {
      if (o instanceof float[] f) {
        writeTag((byte) 21);
        writeTag(FLOAT);
        writeVInt(f.length, daos);
        for (float v : f) {
          daos.writeFloat(v);
        }
      } else {
        super.writeVal(o);
      }
    }
  }

  static MapWriter parseRow(String[] row, boolean legacy) {
    String id;
    String title;
    String article;
    Object article_vector;
    if (row.length < 4) {
      throw new IllegalArgumentException("Invalid row");
    }

    id = row[0];
    title = row[1];
    article = row[2];
    try {
      String json = row[3];
      if (json.charAt(0) != '[') {
        throw new IllegalArgumentException("Invalid json");
      }

      List<Float> floatList = OBJECT_MAPPER.readValue(json, valueTypeRef);

      if (legacy) {
        article_vector = floatList;

      } else {
        float[] floats = new float[floatList.size()];
        for (int i = 0; i < floatList.size(); i++) {
          floats[i] = floatList.get(i);
        }
        article_vector = floats;
      }

      return ew -> {
        ew.put("id", id);
        // ew.put("title", title);
        // ew.put("article", article);
        ew.put("article_vector", article_vector);
      };

    } catch (Exception e) {
      throw new IllegalArgumentException("Invalid JSON");

    }

  }

  private static String[] parseLine(String line) {
    List<String> values = new ArrayList<>();
    StringBuilder currentValue = new StringBuilder();
    boolean inQuotes = false;
    char[] chars = line.toCharArray();

    for (int i = 0; i < chars.length; i++) {
      char currentChar = chars[i];

      if (currentChar == '"') {
        // Toggle the inQuotes flag
        inQuotes = !inQuotes;
      } else if (currentChar == ',' && !inQuotes) {
        // If a comma is found and we're not inside quotes, end the current value
        values.add(currentValue.toString());
        currentValue = new StringBuilder();
      } else {
        // Add the current character to the current value
        currentValue.append(currentChar);
      }
    }

    // Add the last value
    values.add(currentValue.toString());
    return values.toArray(new String[0]);
  }

  static TypeReference<List<Float>> valueTypeRef = new TypeReference<>() {
  };

}