import glob

files = glob.glob('routes/*.py')
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Fix models import
    content = content.replace(
        'from models import Coin, WatchlistCoin, UserSetting, Notification, PriceHistory',
        'from models import Coin, WatchlistCoin, Notification, PriceHistory'
    )
    # Fix credentials import
    content = content.replace(
        'from credentials import Credential, User',
        'from credentials import Credential, User, UserSetting'
    )
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
        
print("Fixed UserSetting import!")
