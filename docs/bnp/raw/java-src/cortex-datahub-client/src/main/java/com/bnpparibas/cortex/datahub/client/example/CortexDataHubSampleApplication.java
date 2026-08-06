package com.bnpparibas.cortex.datahub.client.example;

import java.io.FileOutputStream;
import java.time.LocalDate;
import java.util.List;

public class CortexDataHubSampleApplication {

	private final Oauth2Client oauth2Client;
	private final String apiUrl;

	public CortexDataHubSampleApplication(String oauth2TokenUrl, String apiUrl, String consumerKey, String consumerSecret) {
		this.oauth2Client = new Oauth2Client(oauth2TokenUrl, consumerKey, consumerSecret);
		this.apiUrl = apiUrl;
	}

	public void run() throws Exception {
		String oauth2Token = oauth2Client.getToken();
		System.out.println("got oauth2 token");
		
		ApiClient apiClient = new ApiClient(apiUrl, oauth2Token);
		// call dates endpoint
		List<LocalDate> dates = apiClient.getDates();
		System.out.println(dates);
		
		dates.stream().findFirst().ifPresentOrElse(firstDate -> {
			System.out.println("Fist date collected = " + firstDate);			

			List<String> documents;
			try {
				// call document names endpoint
				documents = apiClient.getDocumentNames(firstDate);
				System.out.println(documents);
				
				documents.stream().findFirst().ifPresentOrElse(firstDocument->{
					System.out.println("Fist document collected = " + firstDocument);
					 
					try {
						// call document endpoint											
						byte[] content = apiClient.getDocument(firstDate, firstDocument);						
						// SAVE THE DOCUMENT LOCALLY
						saveDocument(firstDocument, content);
					} catch (Exception e) {
						throw new RuntimeException(e);
					}			
				}, () -> System.out.println("no documents available to go further"));					
			} catch (Exception e) {
				throw new RuntimeException(e);
			}					
		}, () -> System.out.println("no dates available to go further"));
	}
	
	private void saveDocument(String documentName, byte[] content) throws Exception {
		try (FileOutputStream fos = new FileOutputStream(documentName)) {
			fos.write(content);
			System.out.println("File " + documentName + " saved on your disk");
		}
	}		

	///////////////////////////////////////////////////////////////////////
	//  					main method
	///////////////////////////////////////////////////////////////////////

	public static void main(String[] args) {
		CortexDataHubSampleApplication application = readArgs(args);
		try {			
			application.run();
		} catch (Exception e) {
			System.out.println("couldn't consume the Cortex Datahub api. " + e.getMessage());
			System.exit(1);
		}
	}

	private static CortexDataHubSampleApplication readArgs(String[] args) {
		if (args.length == 1) {
			if ("--help".equals(args[0])) {
				printUsage();
			} else {
				argExit("invalid argument: " + args[0]);
			}
		}
		else if (args.length != 5) {
			argExit("Warning: 4 arguments expected found " + args.length);
		} else {
			int arg = 0;
			if ("--input".equals(args[arg++])) {
				return new CortexDataHubSampleApplication(args[arg++], args[arg++], args[arg++], args[arg++]);
			} else {
				argExit("Error: unrecognized argument: " + args[0]);
			}
		}
		return null;
	}
	
	private static void argExit(String msg) {
		System.err.print(msg);
		printUsage();
		System.exit(1);
	}

	private static void printUsage() {
		System.out.print("\n"
				+ "Usage:\n"
				+ "\t--help\n"
				+ "\t--input <oauth2_url> <api_url> <your consumerKey> <your consumerSecret>\n"
				+ "\t\texample:\n"
				+ "\t\t --input https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub POIUYTREZA azertyuiop");
	}
	
}

