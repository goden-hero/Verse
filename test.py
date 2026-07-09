from pathlib import Path 
from mutagen.easyid3 import EasyID3 as easyid3 

music_rec = Path.home() / "Music" 
count = 0
for i in music_rec.glob("*.mp3"):
    count = count + 1
    print(i.stem)
print(count)
audio = easyid3("/home/hisham/Music/Sixpence None The Richer - Kiss Me.mp3")
print(audio["title"][0])
print(audio["artist"][0])
