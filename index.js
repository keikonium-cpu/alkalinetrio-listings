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

// Load existing gallery data
function loadExistingGallery() {
  if (fs.existsSync(OUTPUT_FILE)) {
    const data = fs.readFileSync(OUTPUT_FILE, "utf8");
    return JSON.parse(data);
  }
  return { page: 1, total: 0, images: [] };
}

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
  console.log(`Found ${elements.length} <li> items on page.`);

  // Load existing data and create a Set of existing IDs for fast lookup
  const existingGallery = loadExistingGallery();
  const existingIds = new Set(existingGallery.images.map(img => img.publicId));
  console.log(`Found ${existingIds.size} existing items in gallery.`);

  const newResults = [];

  for (const el of elements) {
    const id = await el.evaluate((n) => n.id);

    // Skip if this ID already exists
    if (existingIds.has(id)) {
      console.log(`⏭️  Skipping ${id} (already exists)`);
      continue;
    }

    // Check if we've hit the max total items limit
    if (existingGallery.images.length + newResults.length >= MAX_ITEMS) {
      console.log(`⚠️  Reached maximum of ${MAX_ITEMS} items. Stopping capture.`);
      break;
    }

    const filename = `${id}.png`;
    console.log(`📸 Capturing NEW item: ${id}`);
    const buffer = await el.screenshot({ type: "png" });

    console.log(`☁️  Uploading ${filename} to Cloudinary...`);
    const result = await new Promise((resolve, reject) => {
      const upload = cloudinary.uploader.upload_stream(
        {
          folder: "website-screenshots",
          public_id: id,
          overwrite: false, // Changed to false to avoid accidental overwrites
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
    newResults.push({
      url: result.secure_url,
      timestamp,
      publicId: id,
    });
  }

  await browser.close();

  console.log(`✅ Captured ${newResults.length} new items.`);

  // Merge new results with existing data
  const allImages = [...existingGallery.images, ...newResults];
  
  // Trim to MAX_ITEMS if necessary (keeping oldest items)
  const finalImages = allImages.slice(0, MAX_ITEMS);

  const output = {
    page: 1,
    total: finalImages.length,
    images: finalImages,
  };

  fs.mkdirSync("./data", { recursive: true });
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));

  console.log(`✅ Saved gallery JSON: ${OUTPUT_FILE} (${finalImages.length} total items)`);
})();
