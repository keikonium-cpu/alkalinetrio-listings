import puppeteer from "puppeteer";
import { v2 as cloudinary } from "cloudinary";
import dotenv from "dotenv";
import fs from "fs";
dotenv.config();

const URL = process.env.TARGET_URL;
const OUTPUT_FILE = "./data/gallery.json";
const MAX_ITEMS = 60;

cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

(async () => {
const browser = await puppeteer.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
  defaultViewport: { width: 1280, height: 1080 },
});

  const page = await browser.newPage();
  console.log(`Loading ${URL} ...`);
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 60000 });

  const elements = await page.$$(`li[id^="item"]`);
  console.log(`Found ${elements.length} <li> items.`);

  const results = [];

  let count = 0;
  for (const el of elements) {
    const id = await el.evaluate((n) => n.id);
    const filename = `${id}.png`;

    console.log(`📸 Capturing ${id}`);
    const buffer = await el.screenshot({ type: "png" });

    console.log(`☁️ Uploading ${filename} to Cloudinary...`);
    const result = await new Promise((resolve, reject) => {
      const upload = cloudinary.uploader.upload_stream(
        {
          folder: "website-screenshots",
          public_id: id,
          overwrite: true,
          resource_type: "image",
        },
        (error, result) => {
          if (error) reject(error);
          else resolve(result);
        }
      );
      upload.end(buffer);
    });

    const timestamp = new Date().toISOString();
    results.push({
      url: result.secure_url,
      timestamp,
      publicId: id,
    });

    if (++count >= MAX_ITEMS) break;
  }

  await browser.close();

  // Prepare JSON in gallery API format
  const output = {
    page: 1,
    total: results.length,
    images: results,
  };

  fs.mkdirSync("./data", { recursive: true });
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));

  console.log(`✅ Saved gallery JSON: ${OUTPUT_FILE}`);
})();
