import { useEffect, useId, useState } from "react";
import Cropper, { type Area, type Point } from "react-easy-crop";
import page from "../pages/Page.module.css";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import styles from "./PhotoCropper.module.css";
import { FormError } from "./TextField";

type Props = {
  /** The photo to crop; the dialog is open while there is one. */
  file: File | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  /** The chosen square, in the photo's own pixels. */
  onCrop: (area: Area) => void;
};

/** Choose which part of a photo to use: drag it about and zoom in. The round frame shows how
 * it looks beside your name. */
export function PhotoCropper({ file, busy, error, onCancel, onCrop }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [crop, setCrop] = useState<Point>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState<Area | null>(null);
  const zoomId = useId();

  // A fresh start for each photo.
  useEffect(() => {
    if (!file) return;
    const made = URL.createObjectURL(file);
    setUrl(made);
    setCrop({ x: 0, y: 0 });
    setZoom(1);
    setArea(null);
    return () => URL.revokeObjectURL(made);
  }, [file]);

  return (
    <Dialog open={!!file} onClose={onCancel} title="Your photo">
      <div className={styles.frame}>
        {url && (
          <Cropper
            image={url}
            crop={crop}
            zoom={zoom}
            aspect={1}
            cropShape="round"
            showGrid={false}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={(_, pixels) => setArea(pixels)}
          />
        )}
      </div>
      <div className={styles.zoom}>
        <label htmlFor={zoomId}>Zoom</label>
        <input
          id={zoomId}
          type="range"
          min={1}
          max={3}
          step={0.01}
          value={zoom}
          onChange={(event) => setZoom(Number(event.target.value))}
        />
      </div>
      <p className={page.muted}>Drag the photo to move it. Pinch, scroll or use the slider to zoom.</p>
      <FormError message={error} />
      <div className={styles.actions}>
        <Button variant="secondary" block onClick={onCancel}>
          Cancel
        </Button>
        <Button block disabled={!area || busy} onClick={() => area && onCrop(area)}>
          {busy ? "Saving..." : "Use this photo"}
        </Button>
      </div>
    </Dialog>
  );
}
