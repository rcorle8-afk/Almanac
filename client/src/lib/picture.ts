// A chosen photo, made ready to be a group's picture.

const PICTURE_SIDE = 256;
const PICTURE_LIMIT = 2 * 1024 * 1024; // what the server takes

/** A chosen photo as a small centred square, drawn fresh on a canvas: a quick upload, and
 *  nothing of the original file (where and when it was taken) leaves the device. The server
 *  redraws it again regardless. A browser that can't do this sends the file as it is. */
export async function squarePicture(file: File): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const side = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = PICTURE_SIDE;
    const pen = canvas.getContext("2d");
    if (!pen) throw new Error("no canvas");
    pen.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, PICTURE_SIDE, PICTURE_SIDE);
    bitmap.close();
    const drawn = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/webp", 0.9));
    if (drawn) return drawn;
  } catch {
    // fall through to the file itself
  }
  if (file.size > PICTURE_LIMIT) throw new Error("That picture is too big. Keep it under 2 MB.");
  return file;
}
