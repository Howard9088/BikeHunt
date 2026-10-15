'use strict';
// Exercise call-site contracts without rendering the shared exit dialog.
// The real dialog owns navigation; call sites only validate and persist state.
const assert=require('node:assert/strict');
function installExternalExitStub(context){
  let answer=false;
  const prompts=[];
  context.showExternalExit=options=>{
    assert.ok(options&&typeof options==='object','Exit confirmation receives an options object');
    assert.equal(typeof options.url,'string');
    assert.ok(['merchant','amazon','reference'].includes(options.kind),'Exit kind is explicit');
    assert.equal(typeof options.label,'string');
    assert.equal(typeof options.note,'string');
    assert.equal(typeof options.validate,'function','Every exit revalidates its exact context');
    assert.equal(typeof options.onConfirm,'function','State persistence stays in the confirmed callback');
    if(options.validate()!==true)return false;
    prompts.push(options);
    const accepted=typeof answer==='function'?answer(options):answer;
    const stillValid=options.validate()===true;
    if(!accepted){if(options.onCancel)options.onCancel();return false}
    if(!stillValid)return false;
    options.onConfirm();
    if(options.validate()!==true)return false;
    context.window.location.assign(options.url);
    return true;
  };
  // A stale call to the browser-native prompt must fail rather than silently pass.
  context.window.confirm=()=>{throw Error('External exits must use the shared confirmation dialog')};
  return {prompts,setAnswer(value){answer=value}};
}
module.exports={installExternalExitStub};
