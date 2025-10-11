import puppeteer from "puppeteer";
import { v2 as cloudinary } from "cloudinary";
import dotenv from "dotenv";
import fs from "fs";
dotenv.config();

const URL = process.env.TARGET_URL;
const OUTPUT_FILE = "./data/gallery.json";
const MAX_ITEMS_PER_CAPTURE = 60; // Limit per capture session, not total storage
const DELAY_BETWEEN_SCREENSHOTS = 300; // milliseconds (0.3 seconds)

cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

// Helper function to add delay
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

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
  let capturedCount = 0;

  for (const el of elements) {
    const id = await el.evaluate((n) => n.id);

    // Skip if this ID already exists
    if (existingIds.has(id)) {
      console.log(`⏭️  Skipping ${id} (already exists)`);
      continue;
    }

    // Check if we've hit the max per capture limit
    if (capturedCount >= MAX_ITEMS_PER_CAPTURE) {
      console.log(`⚠️  Reached maximum of ${MAX_ITEMS_PER_CAPTURE} items per capture. Stopping.`);
      break;
    }

    const filename = `${id}.webp`;
    console.log(`📸 Capturing NEW item: ${id}`);
    
    // Take screenshot as PNG first (Puppeteer doesn't support WebP directly)
    const buffer = await el.screenshot({ type: "png" });

    // Add delay between screenshots to be respectful to the server
    await delay(DELAY_BETWEEN_SCREENSHOTS);

    console.log(`☁️  Uploading ${filename} to Cloudinary...`);
    const result = await new Promise((resolve, reject) => {
      const upload = cloudinary.uploader.upload_stream(
        {
          folder: "website-screenshots",
          public_id: id,
          format: "webp", // Convert to WebP on Cloudinary
          quality: "auto:best", // High quality, optimized size
          overwrite: false,
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

    capturedCount++;
  }

  await browser.close();

  console.log(`✅ Captured ${newResults.length} new items.`);

  // Merge new results with existing data (no cap on total storage)
  const allImages = [...existingGallery.images, ...newResults];

  const output = {
    page: 1,
    total: allImages.length,
    images: allImages,
  };

  fs.mkdirSync("./data", { recursive: true });
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));

  console.log(`✅ Saved gallery JSON: ${OUTPUT_FILE} (${allImages.length} total items)`);
})();
