package com.bnpparibas.cortex.datahub.client.example;

import java.io.IOException;
import java.net.URI;
import java.security.cert.X509Certificate;

import javax.net.ssl.SSLContext;

import org.apache.hc.client5.http.classic.methods.HttpGet;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClientBuilder;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.impl.routing.DefaultProxyRoutePlanner;
import org.apache.hc.client5.http.io.HttpClientConnectionManager;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactory;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactoryBuilder;
import org.apache.hc.core5.http.ClassicHttpResponse;
import org.apache.hc.core5.http.HttpEntity;
import org.apache.hc.core5.http.HttpException;
import org.apache.hc.core5.http.HttpHeaders;
import org.apache.hc.core5.http.HttpHost;
import org.apache.hc.core5.http.io.HttpClientResponseHandler;
import org.apache.hc.core5.ssl.SSLContexts;

public class HttpClient {

	/**
	 * Create an Http Client instance that skips the ssl server certificate validation in order to simplify the example.<br>
	 * 
	 * Do not do that in production.
	 * 
	 * @return
	 * @throws Exception
	 */
	public static CloseableHttpClient createHttpClient() throws Exception {
		SSLContext sslContext = SSLContexts.custom().loadTrustMaterial(null, (X509Certificate[] chain, String authType) -> true  /* skip ssl certificate verification, don't do this in production */).build();
		SSLConnectionSocketFactory sslSocketFactory = SSLConnectionSocketFactoryBuilder.create().setSslContext(sslContext).build();
		HttpClientConnectionManager connManager = PoolingHttpClientConnectionManagerBuilder.create().setSSLSocketFactory(sslSocketFactory).build();
		HttpClientBuilder httpClientBuilder = HttpClients.custom().setConnectionManager(connManager).evictExpiredConnections();

		if (System.getProperty("http.proxyHost") != null && System.getProperty("http.proxyPort") != null) {
			httpClientBuilder.setRoutePlanner(new DefaultProxyRoutePlanner(new HttpHost(new URI(System.getProperty("http.proxyHost")).getHost(), Integer.parseInt(System.getProperty("http.proxyPort")))));
		}

		return httpClientBuilder.build();
	}


	@FunctionalInterface
	public interface ParserFunction<T, R> {
	    R apply(T t) throws HttpException, IOException;
	}
	
	/**
	 * Make a call to the Cortex DataHub on 'endpointUrl' end point
	 * @param class1 
	 * 
	 * @param oauth2Token, endpointUrl
	 * @return
	 * @throws Exception
	 */
	public static <T> T callApiWithToken(String oauth2Token, String endpointUrl, String acceptValue, ParserFunction<HttpEntity, T> parser) throws Exception {
		System.out.println("\n--- endpoint : " + endpointUrl);
		HttpGet httpGetDatesRequest = new HttpGet(endpointUrl);
		// use the access token for the bearer token
		httpGetDatesRequest.setHeader(HttpHeaders.AUTHORIZATION, "Bearer " + oauth2Token);
		httpGetDatesRequest.setHeader(HttpHeaders.ACCEPT, acceptValue);

		try (CloseableHttpClient httpClient = HttpClient.createHttpClient()) {
			return httpClient.execute(httpGetDatesRequest, (HttpClientResponseHandler<? extends T>) (ClassicHttpResponse response) -> {
				if (response.getCode() == 200) {
					HttpEntity entity = response.getEntity();
					if (entity != null) {
						return parser.apply(entity);
					}
				} else {
					throw new RuntimeException("api call error : " + response.getCode() + " " + response.getReasonPhrase());
				}
				return null;
			});			
		}
	}
	
}
