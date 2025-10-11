import { v2 as cloudinary } from "cloudinary";
import dotenv from "dotenv";
import fs from "fs";
dotenv.config();

const OUTPUT_FILE = "./data/eBaySales.json";
const ITEMS_PER_PAGE = 60;
const CLOUDINARY_FOLDER = "website-screenshots";

cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

// Convert flat array to paginated structure
function createPaginatedStructure(allImages) {
  const pages = [];
  
  for (let i = 0; i < allImages.length; i += ITEMS_PER_PAGE) {
    const pageImages = allImages.slice(i, i + ITEMS_PER_PAGE);
    pages.push({
      page: Math.floor(i / ITEMS_PER_PAGE) + 1,
      total: pageImages.length,
      images: pageImages
    });
  }
  
  return { pages };
}

// Recursively fetch all resources from Cloudinary
async function getAllCloudinaryImages(nextCursor = null, allResources = []) {
  const options = {
    type: "upload",
    prefix: CLOUDINARY_FOLDER,
    max_results: 500, // Max per request
    resource_type: "image"
  };
  
  if (nextCursor) {
    options.next_cursor = nextCursor;
  }
  
  console.log(`Fetching images from Cloudinary... (${allResources.length} so far)`);
  
  const result = await cloudinary.api.resources(options);
  allResources.push(...result.resources);
  
  console.log(`Found ${result.resources.length} images in this batch`);
  
  // If there are more results, fetch them recursively
  if (result.next_cursor) {
    console.log(`More images available, fetching next batch...`);
    return getAllCloudinaryImages(result.next_cursor, allResources);
  }
  
  return allResources;
}

(async () => {
  try {
    console.log("🔄 Starting Cloudinary sync...");
    console.log(`📁 Fetching all images from folder: ${CLOUDINARY_FOLDER}`);
    
    // Fetch all images from Cloudinary
    const resources = await getAllCloudinaryImages();
    
    console.log(`✅ Found ${resources.length} total images in Cloudinary`);
    
    // Filter to only items that match the pattern "item*"
    const filteredResources = resources.filter(r => {
      const publicId = r.public_id.split('/').pop();
      return publicId.startsWith('item');
    });
    
    console.log(`🔍 Filtered to ${filteredResources.length} items matching pattern "item*"`);
    
    // Transform to our JSON format
    const allImages = filteredResources.map(resource => {
      const publicId = resource.public_id.split('/').pop(); // Get filename without folder path
      
      return {
        url: resource.secure_url,
        timestamp: resource.created_at || new Date().toISOString(),
        publicId: publicId
      };
    });
    
    // Sort by created date (newest first)
    allImages.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    console.log(`📊 Creating paginated structure with ${ITEMS_PER_PAGE} items per page...`);
    
    // Convert to paginated structure
    const output = createPaginatedStructure(allImages);
    
    // Save to file
    fs.mkdirSync("./data", { recursive: true });
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
    
    const totalPages = output.pages.length;
    console.log(`✅ Sync complete!`);
    console.log(`📄 Saved to: ${OUTPUT_FILE}`);
    console.log(`📦 Total items: ${allImages.length}`);
    console.log(`📖 Total pages: ${totalPages}`);
    console.log(`\nBreakdown by page:`);
    output.pages.forEach(page => {
      console.log(`   Page ${page.page}: ${page.total} items`);
    });
    
  } catch (error) {
    console.error("❌ Error syncing with Cloudinary:", error);
    process.exit(1);
  }
})();
