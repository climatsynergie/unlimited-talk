export function silentWav() {
  const body = Buffer.alloc(32044);
  body.write("RIFF", 0);
  body.writeUInt32LE(32036, 4);
  body.write("WAVEfmt ", 8);
  body.writeUInt32LE(16, 16);
  body.writeUInt16LE(1, 20);
  body.writeUInt16LE(2, 22);
  body.writeUInt32LE(8000, 24);
  body.writeUInt32LE(32000, 28);
  body.writeUInt16LE(4, 32);
  body.writeUInt16LE(16, 34);
  body.write("data", 36);
  body.writeUInt32LE(32000, 40);
  return body;
}
