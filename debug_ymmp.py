import os, json, glob

dirs = sorted([d for d in glob.glob('output/*') if os.path.isdir(d)], key=os.path.getmtime, reverse=True)
print('Directories:', [os.path.basename(d) for d in dirs[:3]])

for d in dirs:
    ymmp_files = glob.glob(os.path.join(d, '*.ymmp'))
    if ymmp_files:
        print('\nLatest ymmp:', ymmp_files[0])
        with open(ymmp_files[0], 'r', encoding='utf-16') as f:
            data = json.load(f)
        items = data['Timelines'][0]['Items']
        print(f'Total items: {len(items)}')
        print()
        for item in items[:20]:
            type_str = item.get('$type', '?').split('.')[-1].replace(', YukkuriMovieMaker', '')
            frame = item.get('Frame', 0)
            length = item.get('Length', 0)
            serif = item.get('Serif', '')[:40]
            hatsuon = item.get('Hatsuon', '[N/A]')[:30]
            filepath = os.path.basename(item.get('FilePath', ''))[:30]
            char = item.get('CharacterName', '')
            print(f'[{type_str}] Frame={frame} Len={length}')
            if serif:
                print(f'  Serif   : {serif}')
                print(f'  Hatsuon : {hatsuon}')
                print(f'  Char    : {char}')
            else:
                print(f'  File    : {filepath}')
            print()
        break
