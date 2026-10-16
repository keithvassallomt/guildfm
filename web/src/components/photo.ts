import type { Area } from "react-easy-crop";

const SIZE = 256; // pixels: sharp at the largest size an avatar is shown, on any screen

/** Opens a photo, or says it can't be: HEIC photos from iPhones only open in Safari. */
export async function openPhoto(file: File): Promise<ImageBitmap> {
  try {
    return await createImageBitmap(file);
  } catch {
    throw new Error("That photo couldn't be opened. Try a JPEG or PNG.");
  }
}

/** The part of a photo someone chose (`area`, in the photo's own pixels), shrunk to a square
 * avatar ready to upload. Shrinking it here keeps uploads small, and drops the original's
 * location and camera details. */
export async function croppedPhoto(file: File, area: Area): Promise<Blob> {
  const image = await openPhoto(file);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  canvas
    .getContext("2d")
    ?.drawImage(image, area.x, area.y, area.width, area.height, 0, 0, SIZE, SIZE);
  image.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("That photo couldn't be shrunk."))),
      "image/jpeg",
      0.88,
    ),
  );
}
