import os
import glob

files = glob.glob('routes/*.py')
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    new_content = content.replace(
        'from models import Coin, Transaction, WatchlistCoin, UserSetting, Notification',
        'from models import Coin, WatchlistCoin, UserSetting, Notification, PriceHistory'
    )
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(new_content)
        
print("Removed Transaction from models imports in all files!")
