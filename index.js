import puppeteer from "puppeteer";
import { v2 as cloudinary } from "cloudinary";
import dotenv from "dotenv";
dotenv.config();

const URL = process.env.TARGET_URL; // page containing <li id="item...">
const MAX_ITEMS = 60; // optional limit

// Configure Cloudinary
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    defaultViewport: { width: 1280, height: 1080 },
  });

  const page = await browser.newPage();
  console.log(`Loading ${URL} ...`);
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 60000 });

  // Select all <li> elements where id starts with "item"
  const elements = await page.$$(`li[id^="item"]`);
  console.log(`Found ${elements.length} elements`);

  let count = 0;
  for (const el of elements) {
    const id = await el.evaluate((n) => n.id);
    const filename = `${id}.png`;

    console.log(`📸 Capturing ${id}`);
    const buffer = await el.screenshot({ type: "png" });

    console.log(`☁️ Uploading to Cloudinary...`);
    await cloudinary.uploader.upload_stream(
      {
        folder: "website-screenshots",
        public_id: id,
        overwrite: true,
        resource_type: "image",
      },
      (error, result) => {
        if (error) console.error("❌ Upload failed:", error);
        else console.log("✅ Uploaded:", result.secure_url);
      }
    ).end(buffer);

    if (++count >= MAX_ITEMS) break;
  }

  await browser.close();
  console.log("✅ All screenshots done.");
})();