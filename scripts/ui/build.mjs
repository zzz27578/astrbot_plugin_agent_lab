import {build} from 'esbuild';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const result=await build({
  entryPoints:['connector-entry.js'],
  outfile:'../../pages/agent-lab/vendor/connectors.js',
  bundle:true,minify:true,format:'esm',platform:'browser',target:'es2020',legalComments:'eof',metafile:true,
  // The path functions do not use D3. D3's top-level transition registration
  // otherwise survives tree shaking through XYFlow's public barrel export.
  // Mark only these imports side-effect free; any genuinely used export stays.
  plugins:[{name:'isolated-paths',setup(builder){
    builder.onResolve({filter:/^d3-/},args=>({path:require.resolve(args.path),sideEffects:false}));
  }}],
});
const inputs=Object.values(result.metafile.outputs).flatMap(output=>Object.entries(output.inputs));
if(inputs.some(([file,info])=>file.includes('node_modules/d3-')&&info.bytesInOutput>0)){
  throw Error('Unexpected D3 runtime in path-only bundle; review its use and licenses before shipping.');
}
fs.copyFileSync('node_modules/@xyflow/system/LICENSE','../../pages/agent-lab/vendor/XYFLOW-LICENSE');
console.log('Built isolated XYFlow connectors.');
