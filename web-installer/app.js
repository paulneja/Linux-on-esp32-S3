const variants = {
  headless: { title: 'Linux without a display', file: 'firmware/headless-v1.bin' },
  paperboard: { title: 'Linux for Paperboard', file: 'firmware/paperboard-v3.bin' },
};
function selectVariant(value) {
  document.querySelector('#install-title').textContent = variants[value].title;
  document.querySelector('#download').href = variants[value].file;
  for (const name of Object.keys(variants)) document.querySelector(`#${name}-install`).hidden = name !== value;
}
for (const radio of document.querySelectorAll('[name="variant"]')) radio.addEventListener('change', () => selectVariant(radio.value));
selectVariant(document.querySelector('[name="variant"]:checked').value);
const status = document.querySelector('#browser-status');
if (!window.isSecureContext || location.protocol === 'file:') {
  status.textContent = 'Open this page over HTTPS or http://127.0.0.1:8080.';
} else if (!('serial' in navigator)) {
  status.textContent = 'USB installation needs desktop Google Chrome with Web Serial.';
} else {
  try {
    await import('./vendor/install-button.js');
    await customElements.whenDefined('esp-web-install-button');
    for (const button of document.querySelectorAll('button[slot="activate"]')) button.disabled = false;
    status.textContent = 'Your browser supports USB installation.';
  } catch (error) {
    status.textContent = 'USB installer failed to load. Refresh the page and check the vendor folder.';
    console.error(error);
  }
}
