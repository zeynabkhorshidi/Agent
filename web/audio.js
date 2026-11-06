/* صوت ضبط‌شده به PCM WAV تک‌کاناله 16kHz تبدیل می‌شود؛ متن یا سبد دست‌کاری نمی‌شود. */
export function pcmWav(buffer){
 const count=buffer.length,out=new ArrayBuffer(44+count*2),view=new DataView(out);
 const text=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));};
 text(0,'RIFF');view.setUint32(4,36+count*2,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,count*2,true);
 const channels=Array.from({length:buffer.numberOfChannels},(_,i)=>buffer.getChannelData(i));
 for(let i=0;i<count;i++){let sample=0;for(const channel of channels)sample+=channel[i]/channels.length;sample=Number.isFinite(sample)?Math.max(-1,Math.min(1,sample)):0;view.setInt16(44+i*2,sample<0?sample*32768:sample*32767,true);}
 return new Blob([out],{type:'audio/wav'});
}
export async function speechWav(blob){
 const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;
 if(!Offline)return null;
 try{const context=new Offline(1,1,16000);const decoded=await context.decodeAudioData(await blob.arrayBuffer());if(!decoded.length)return null;return pcmWav(decoded);}catch{return null;}
}
