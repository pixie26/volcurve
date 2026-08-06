import sys
import urllib3
from shared_auth import oauth2, initialize_token_management

def main(argv):
    # Disable SSL warnings
    urllib3.disable_warnings()

    # Check number of arguments
    argSize = len(argv)
    if (argSize == 4):
        http_proxy = None
    elif (argSize == 5):
        http_proxy = {
            'http': argv[4],
            'https': argv[4],
        }
    else:
        print("#######################################################################")
        print("WARNING: 4 or 5 arguments expected")
        print("USAGE 4 arguments:")
        print("python CortexDatahub_XXXX_sample.py <url auth> <url endpoints> <your consumerKey> <your consumerSecret>")
        print("ex:")
        print("python CortexDatahub_XXXX_sample.py https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub scCrhrlusfMMd4 rjspodi")
        print("USAGE 5 arguments:")
        print("python CortexDatahub_XXXX_sample.py <url auth> <url endpoints> <your consumerKey> <your consumerSecret> <your http proxy>")
        print("ex:")
        print("python CortexDatahub_XXXX_sample.py https://api.cib.bnpparibas.com/oauth2/v1/token https://api.cib.bnpparibas.com/gm-cortex-datahub scCrhrlusfMMd4 rjspodi myCompany.intranet:8080")
        print("#######################################################################")
        sys.exit(2)

    # Initialiser la gestion du token
    initialize_token_management(argv[2], argv[3], http_proxy, argv[0])

    # AUTHENTICATION
    headers = oauth2()

    return argv[1], headers, http_proxy