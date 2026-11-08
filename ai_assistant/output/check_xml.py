import glob
import xml.etree.ElementTree as ET

files = glob.glob('views/*.xml') + glob.glob('data/*.xml')
for path in files:
    ET.parse(path)
print('valid XML:', len(files), 'files')
