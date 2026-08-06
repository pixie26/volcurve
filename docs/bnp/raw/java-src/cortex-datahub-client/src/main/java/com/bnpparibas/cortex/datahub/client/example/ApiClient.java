package com.bnpparibas.cortex.datahub.client.example;

import static com.bnpparibas.cortex.datahub.client.example.HttpClient.callApiWithToken;

import java.io.IOException;
import java.time.LocalDate;
import java.util.List;

import org.apache.hc.core5.http.HttpEntity;
import org.apache.hc.core5.http.ParseException;
import org.apache.hc.core5.http.io.entity.EntityUtils;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonMappingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

public class ApiClient {

	private final String apiUrl;
	private final String oauth2Token;
	
	public ApiClient(String apiUrl, String oauth2Token) {
		this.apiUrl = apiUrl;
		this.oauth2Token = oauth2Token;
	}

	/**
	 * Make a call to the Cortex DataHub "dates" end point
	 * 
	 * @return
	 * @throws Exception
	 */
	public List<LocalDate> getDates() throws Exception {
		return callApiWithToken(oauth2Token, 
				apiUrl + "/v1/market-data/dates", "application/json", 
				entity -> parseJson(entity, DateListDto.class)).getDates();		
	}
	
	/**
	 * Make a call to the Cortex DataHub "document names" end point
	 * 
	 * @return
	 * @throws Exception
	 */
	public List<String> getDocumentNames(LocalDate firstDate) throws Exception {
		return callApiWithToken(oauth2Token, 
				apiUrl + "/v1/market-data/dates/" + firstDate + "/documents", "application/json", 
				entity -> parseJson(entity, DocumentListDto.class)).getDocuments();
	}	

	private static <T> T parseJson(HttpEntity entity, Class<T> type)
			throws JsonProcessingException, JsonMappingException, IOException, ParseException {
		return new ObjectMapper().registerModule(new JavaTimeModule()).readValue(EntityUtils.toString(entity), type);
	}
	
	/**
	 * Make a call to the Cortex DataHub "document" end point
	 * 
	 * @return
	 * @throws Exception
	 */
	public byte[] getDocument(LocalDate firstDate, String documentName) throws Exception {
		String endpointUrl = apiUrl + "/v1/market-data/dates/" + firstDate + "/documents/" + documentName;
		return callApiWithToken(oauth2Token, endpointUrl, "application/octet-stream", entity -> EntityUtils.toByteArray(entity));
	}		

}
