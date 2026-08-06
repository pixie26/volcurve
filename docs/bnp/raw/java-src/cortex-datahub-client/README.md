# Cortex DataHub client sample application

This project contains a single file application that demonstrates how to connect and use the API with java.

It is intended to be used by the external clients as running sample.

The purpose of this code is to be copied onto the DevPortal, in the documentation section of the API.

It does not depend on the rest of the project, it is totally independent.

It uses the Apache httpclient5 library and java 17.

### build the application

Build the application with maven

    mvn package

### run the application
   
    java -jar target/cortex-datahub-client.jar --input https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub <consumerKey> <consumerSecret>

If you are running the application behind a proxy you can set the system properties `http.proxyHost` and `http.proxyPort` on the command line above in adding the following arguments:

    java -Dhttp.proxyHost=http://YOUR_PROXY_HOST -Dhttp.proxyPort=YOUR_PROXY_PORT -jar target/cortex-datahub-client.jar --input https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub <consumerKey> <consumerSecret>