package com.bnpparibas.cortex.datahub.client.example;

import static com.bnpparibas.cortex.datahub.client.example.HttpClient.createHttpClient;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import org.apache.hc.client5.http.classic.methods.HttpPost;
import org.apache.hc.client5.http.entity.UrlEncodedFormEntity;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.utils.Base64;
import org.apache.hc.core5.http.ClassicHttpResponse;
import org.apache.hc.core5.http.HttpEntity;
import org.apache.hc.core5.http.HttpHeaders;
import org.apache.hc.core5.http.io.entity.EntityUtils;
import org.apache.hc.core5.http.message.BasicNameValuePair;

import com.fasterxml.jackson.databind.ObjectMapper;

public class Oauth2Client {

	private static final String GRANT_TYPE         = "grant_type";
	private static final String CLIENT_CREDENTIALS = "client_credentials";

	private final String oauth2TokenUrl;
	private final String consumerKey; 
	private final String consumerSecret;
	
	public Oauth2Client(String oauth2TokenUrl, String consumerKey, String consumerSecret) {
		this.oauth2TokenUrl = oauth2TokenUrl;
		this.consumerKey = consumerKey;
		this.consumerSecret = consumerSecret;
	}

	/** Retrieve the access token from the oauth2 end point
	 * 
	 * @return
	 * @throws Exception
	 */
	public String getToken() throws Exception {
		HttpPost httpPostRequest = new HttpPost(oauth2TokenUrl);
		
		// set the "grant_type" to "client_credentials" 
		httpPostRequest.setEntity(new UrlEncodedFormEntity(Arrays.asList(new BasicNameValuePair(GRANT_TYPE, CLIENT_CREDENTIALS))));

		// set the Authorization header, with the consumer key and secret
		httpPostRequest.setHeader(HttpHeaders.AUTHORIZATION, "Basic " + new String(Base64.encodeBase64((consumerKey + ":" + consumerSecret).getBytes(StandardCharsets.ISO_8859_1))));

		try (CloseableHttpClient httpClient = createHttpClient()) {
			return httpClient.execute(httpPostRequest, (ClassicHttpResponse response) -> {
				// parse the result to retrieve the access token
				if (response.getCode() == 200) {
					HttpEntity entity = response.getEntity();
					if (entity != null) {
						return new ObjectMapper().readValue(EntityUtils.toString(entity), OauthResponseDto.class).getAccessToken();
					}
				} else {
					throw new RuntimeException("could not get the oauth2 token code=" + response.getCode() + " " + response.getReasonPhrase());
				}
				return null;
			});
		}
	}

}
