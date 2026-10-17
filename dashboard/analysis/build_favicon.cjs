// Keep the supplied illustration's proportions inside a square, transparent tab icon.
// Embed the original PNG because favicons cannot rely on external SVG image resources.
const fs=require('node:fs'),path=require('node:path');
const dist=path.join(__dirname,'../dist');
const png=fs.readFileSync(path.join(dist,'favicon.png')).toString('base64');
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'+
 '  <image width="64" height="64" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,'+png+'"/>\n</svg>\n';
fs.writeFileSync(path.join(dist,'favicon.svg'),svg);
