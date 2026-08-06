package com.bnpparibas.cortex.datahub.client.example;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public final class OauthResponseDto {

	@JsonProperty("access_token")
	private String accessToken;

	public String getAccessToken() {
		return accessToken;
	}
}