#!/usr/bin/env node
// Use Bubblewrap's pinned generator, with checked-in web assets as inputs.
// Local inputs keep generation reproducible before website deployment.
const fs = require('node:fs/promises');
const path = require('node:path');
const {TwaManifest, TwaGenerator, ConsoleLog} = require('@bubblewrap/core');
const {fetchUtils} = require('@bubblewrap/core/dist/lib/FetchUtils');

async function main() {
  const root = path.resolve(__dirname, '..');
  const web = path.resolve(root, '../../app/web');
  const config = JSON.parse(await fs.readFile(path.join(root, 'twa-manifest.json'), 'utf8'));
  const inputs = new Map([
    [config.iconUrl, ['icons/verse-512.png', 'image/png']],
    [config.maskableIconUrl, ['icons/verse-maskable-512.png', 'image/png']],
    [config.webManifestUrl, ['manifest.webmanifest', 'application/manifest+json']],
  ]);
  fetchUtils.fetch = async url => {
    const input = inputs.get(String(url));
    if (!input) throw new Error(`Unexpected remote build input: ${url}`);
    return new Response(await fs.readFile(path.join(web, input[0])), {
      status: 200, headers: {'content-type': input[1]},
    });
  };
  const manifest = new TwaManifest(config);
  const error = manifest.validate();
  if (error) throw new Error(error);
  await new TwaGenerator().createTwaProject(root, manifest, new ConsoleLog('Verse'));
  // Keep the helper version explicit; use Maven Central instead of retired JCenter.
  const gradlePath = path.join(root, 'app/build.gradle');
  let gradle = await fs.readFile(gradlePath, 'utf8');
  gradle = gradle.replace(/com\.google\.androidbrowserhelper:androidbrowserhelper:[^'"\s]+/g,
    'com.google.androidbrowserhelper:androidbrowserhelper:2.7.4');
  gradle = gradle.replaceAll('jcenter()', 'mavenCentral()');
  await fs.writeFile(gradlePath, gradle);
  const rootGradlePath = path.join(root, 'build.gradle');
  await fs.writeFile(rootGradlePath, (await fs.readFile(rootGradlePath, 'utf8')).replaceAll('jcenter()', 'mavenCentral()'));
  const wrapper = path.join(root, 'gradle/wrapper/gradle-wrapper.properties');
  await fs.appendFile(wrapper, '\ndistributionSha256Sum=f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6\n');
  console.log(`Generated ${config.packageId} ${config.appVersion} (${config.appVersionCode}) with Bubblewrap.`);
}
main().catch(error => {console.error(error); process.exitCode = 1;});
