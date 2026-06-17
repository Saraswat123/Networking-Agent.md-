import sys
sys.path.insert(0, 'agents')
from dotenv import load_dotenv
load_dotenv('.env')
from x_agent import authorize
authorize()
