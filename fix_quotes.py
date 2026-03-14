import glob

def fix_quotes():
    files = glob.glob('/home/mumulhl/UmaExporter/src/ui/**/*.py', recursive=True)
    for f in files:
        with open(f, 'r', encoding='utf-8') as file:
            content = file.read()
        
        if '\\\"' in content:
            content = content.replace('\\\"', '\"')
            with open(f, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f'Fixed {f}')

if __name__ == '__main__':
    fix_quotes()
