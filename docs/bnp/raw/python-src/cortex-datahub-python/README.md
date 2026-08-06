# Cortex DataHub python client sample code

This distribution contains a bunch of python samples that demonstrate how to connect and use the API with python:
- `Cortex_DataHub_API_Curves_sample.py` shows how to make a call to the Curves endpoint. This script requires the access to the Volatility data.
- `Cortex_DataHub_API_Equity_Volatility_sample.py` shows how to make a call to the Volatility endpoint. This script requires the access to the Volatility data.
- `Cortex_DataHub_API_Equity_Volatility_Intraday_sample.py` shows how to make a call to the Volatility endpoint every 15 minutes. This script requires the access to the olatility data.
- `Cortex_DataHub_API_File_sample.py` shows how to make a call to the endpoint that gives access to the files you have access to. This script only requires the access to the file api.
- `Cortex_DataHub_API_Series_IRS_sample.py` shows how to make a call to the IRS Series. This script requires the access to the IRS data.
- `Cortex_DataHub_API_Series_Quantvault_sample.py` shows how to make a call to the QuantVault Series enpoint. This script requires the access to the QuantVault data.
- `Cortex_DataHub_API_Series_Swaption_Sample.py` shows how to make a call to the Swaption Series enpoint. This script requires the access to the Swaption data.
- `Cortex_DataHub_API_ThematicBasket_sample.py` shows how to make a call to the endpoint that gives access to the thematic basket data if you have access to. This script requires the access to the thematic basket data.

This is intended to be used by the external clients.

## Requirements

This code uses 'requests', 'urllib3', 'schedule' libraries and python3. 

If the modules are not installed yet, run the following command: 

	pip install -r requirements.txt	

## Run the application



### Direct access to the internet

Launch the python script you want, either `Cortex_DataHub_API_sample.py`, `Cortex_DataHub_API_File_sample.py` or `Cortex_DataHub_API_Data_sample.py` with four arguments

	python Cortex_DataHub_API_sample.py <url auth> <url endpoints> <your consumerKey> <your consumerSecret>

Example: 
- replace `scCrhrlusfMMd4` with your "consumerKey"
- replace `rjspodi` with your "consumerSecret".

    python Cortex_DataHub_API_sample.py  https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub scCrhrlusfMMd4 rjspodi

    
### Running the application behind a proxy

When running behind a coporate proxy, a fifth argument must be added with the address of your corporate proxy.

Launch the python script you want, either `Cortex_DataHub_API_sample.py`, `Cortex_DataHub_API_File_sample.py` or `Cortex_DataHub_API_Data_sample.py` with five arguments

	python Cortex_DataHub_API_XXXX_sample.py <url auth> <url endpoints> <your consumerKey> <your consumerSecret> <your http proxy>

Example: 
- replace `XXXX` with the real name of the script
- replace `scCrhrlusfMMd4` with your "consumerKey"
- replace `rjspodi` with your "consumerSecret".
- replace `your http proxy` with the `http://host:port of your corporate proxy

    python Cortex_DataHub_API_Equity_Volatility_sample.py https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub scCrhrlusfMMd4 rjspodi http://myCompany.intranet:8080
