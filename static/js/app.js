class VideoConverter {
    constructor() {
        this.currentFileId = null;
        this.downloadUrl = null;
        this.queueInterval = null;
        this.initializeEventListeners();
        this.checkApiStatus();
        // Check queue status immediately on page load
        this.updateQueueStatus();
        this.startQueuePolling();
    }

    initializeEventListeners() {
        // Form submission
        document.getElementById('uploadForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFileUpload();
        });

        // CSV form submission
        document.getElementById('csvUploadForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleCsvUpload();
        });

        // Download button
        document.getElementById('downloadBtn').addEventListener('click', () => {
            this.downloadFile();
        });

        // Convert another button
        document.getElementById('convertAnotherBtn').addEventListener('click', () => {
            this.resetForm();
        });

        // Try again button
        document.getElementById('tryAgainBtn').addEventListener('click', () => {
            this.resetForm();
        });

        // File input change
        document.getElementById('fileInput').addEventListener('change', (e) => {
            this.handleFileInputChange(e.target);
        });

        // CSV file input change
        document.getElementById('csvFileInput').addEventListener('change', (e) => {
            this.handleCsvFileInputChange(e.target);
        });

        // Bulk mode checkbox
        document.getElementById('bulkModeCheckbox').addEventListener('change', (e) => {
            this.toggleBulkMode(e.target.checked);
        });

        // Refresh queue button
        document.getElementById('refreshQueueBtn').addEventListener('click', () => {
            this.updateQueueStatus();
        });
    }

    handleFileInputChange(input) {
        const files = input.files;
        if (!files || files.length === 0) return;

        // Update file count display
        const bulkMode = document.getElementById('bulkModeCheckbox').checked;
        if (bulkMode && files.length > 1) {
            this.showToast(`${files.length} files selected for bulk conversion`, 'info');
        } else if (files.length > 1) {
            // Warn user about multiple files in single mode
            this.showToast('Multiple files detected. Enable bulk mode for queue processing.', 'warning');
        }

        // Validate each file
        for (let i = 0; i < files.length; i++) {
            if (!this.validateFile(files[i])) {
                input.value = ''; // Clear invalid selection
                return;
            }
        }
    }

    validateFile(file) {
        // Check file size (500MB limit)
        const maxSize = 500 * 1024 * 1024; // 500MB in bytes
        if (file.size > maxSize) {
            this.showToast(`File "${file.name}" is too large. Maximum size is 500MB.`, 'error');
            return false;
        }

        // Check file type
        if (!file.type.includes('webm') && !file.name.toLowerCase().endsWith('.webm')) {
            this.showToast(`File "${file.name}" is not a valid WebM file.`, 'error');
            return false;
        }

        return true;
    }

    handleCsvFileInputChange(input) {
        const file = input.files[0];
        if (!file) return;

        // Validate CSV file
        if (!this.validateCsvFile(file)) {
            input.value = ''; // Clear invalid selection
            return;
        }
    }

    validateCsvFile(file) {
        // Check file size (500MB limit)
        const maxSize = 500 * 1024 * 1024; // 500MB in bytes
        if (file.size > maxSize) {
            this.showToast(`File "${file.name}" is too large. Maximum size is 500MB.`, 'error');
            return false;
        }

        // Check file type
        if (!file.type.includes('csv') && !file.name.toLowerCase().endsWith('.csv')) {
            this.showToast(`File "${file.name}" is not a valid CSV file.`, 'error');
            return false;
        }

        return true;
    }

    async handleCsvUpload() {
        const csvFileInput = document.getElementById('csvFileInput');
        const durationInput = document.getElementById('durationInput');
        const file = csvFileInput.files[0];
        const duration = parseInt(durationInput.value) || 3;

        if (!file) {
            this.showToast('Please select a CSV file first.', 'error');
            return;
        }

        // Validate file
        if (!this.validateCsvFile(file)) {
            return;
        }

        // Show progress
        this.showProgress();
        this.disableCsvForm();

        const formData = new FormData();
        formData.append('file', file);
        formData.append('duration', duration);

        try {
            const response = await axios.post('/api/csv-to-video', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data'
                },
                timeout: 300000 // 5 minutes timeout
            });

            const data = response.data;
            
            if (data.success) {
                this.currentFileId = data.file_id;
                this.downloadUrl = data.download_url;
                this.showCsvSuccess(data.original_filename);
            } else {
                this.showError(data.error || 'Video creation failed');
            }
        } catch (error) {
            console.error('CSV upload error:', error);
            
            if (error.response) {
                // Server responded with error status
                const errorMessage = error.response.data.error || `Server error: ${error.response.status}`;
                this.showError(errorMessage);
            } else if (error.code === 'ECONNABORTED') {
                // Timeout
                this.showError('Video creation timed out. The file may be too large or complex.');
            } else {
                // Network or other error
                this.showError('Network error. Please check your connection and try again.');
            }
        } finally {
            this.hideProgress();
            this.enableCsvForm();
        }
    }

    showCsvSuccess(originalFilename) {
        const resultsCard = document.getElementById('resultsCard');
        const successResult = document.getElementById('successResult');
        const errorResult = document.getElementById('errorResult');

        resultsCard.classList.remove('d-none');
        successResult.classList.remove('d-none');
        errorResult.classList.add('d-none');

        // Update success message with filename
        const cardText = successResult.querySelector('.card-text');
        cardText.textContent = `Your video has been successfully created from the CSV file "${originalFilename}".`;
        
        // Update the title to reflect CSV to video conversion
        const cardTitle = successResult.querySelector('.card-title');
        cardTitle.innerHTML = '<i class="fas fa-check-circle me-2"></i> Video Creation Successful!';
    }

    disableCsvForm() {
        document.getElementById('csvConvertBtn').disabled = true;
        document.getElementById('csvFileInput').disabled = true;
        document.getElementById('durationInput').disabled = true;
        document.getElementById('csvConvertBtn').innerHTML = `
            <i class="fas fa-spinner fa-spin me-2"></i>
            Processing...
        `;
    }

    enableCsvForm() {
        document.getElementById('csvConvertBtn').disabled = false;
        document.getElementById('csvFileInput').disabled = false;
        document.getElementById('durationInput').disabled = false;
        document.getElementById('csvConvertBtn').innerHTML = `
            <i class="fas fa-film me-2"></i>
            Create Video from CSV
        `;
    }

    toggleBulkMode(enabled) {
        const queueCard = document.getElementById('queueStatusCard');
        if (enabled) {
            queueCard.classList.remove('d-none');
            this.showToast('Bulk conversion mode enabled. Queue status will be displayed.', 'info');
        } else {
            queueCard.classList.add('d-none');
        }
    }

    async handleFileUpload() {
        const fileInput = document.getElementById('fileInput');
        const files = fileInput.files;
        const bulkMode = document.getElementById('bulkModeCheckbox').checked;

        if (!files || files.length === 0) {
            this.showToast('Please select file(s) first.', 'error');
            return;
        }

        // Validate all files
        for (let i = 0; i < files.length; i++) {
            if (!this.validateFile(files[i])) {
                return;
            }
        }

        if (bulkMode || files.length > 1) {
            // Bulk conversion mode
            await this.handleBulkUpload(files);
        } else {
            // Single file conversion mode
            await this.handleSingleUpload(files[0]);
        }
    }

    async handleSingleUpload(file) {
        // Show progress
        this.showProgress();
        this.disableForm();

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await axios.post('/api/convert', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data'
                },
                timeout: 300000 // 5 minutes timeout
            });

            const data = response.data;
            
            if (data.success) {
                this.currentFileId = data.file_id;
                this.downloadUrl = data.download_url;
                this.showSuccess(data.original_filename);
            } else {
                this.showError(data.error || 'Conversion failed');
            }
        } catch (error) {
            console.error('Upload error:', error);
            
            if (error.response) {
                // Server responded with error status
                const errorMessage = error.response.data.error || `Server error: ${error.response.status}`;
                this.showError(errorMessage);
            } else if (error.code === 'ECONNABORTED') {
                // Timeout
                this.showError('Conversion timed out. The file may be too large or complex.');
            } else {
                // Network or other error
                this.showError('Network error. Please check your connection and try again.');
            }
        } finally {
            this.hideProgress();
            this.enableForm();
        }
    }

    async handleBulkUpload(files) {
        // Show progress
        this.showProgress();
        this.disableForm();

        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }

        try {
            const response = await axios.post('/api/bulk-convert', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data'
                },
                timeout: 300000 // 5 minutes timeout
            });

            const data = response.data;
            
            if (data.success) {
                this.showBulkSuccess(data);
                // Start polling queue status
                this.startQueuePolling();
            } else {
                this.showError(data.error || 'Bulk conversion failed');
            }
        } catch (error) {
            console.error('Bulk upload error:', error);
            
            if (error.response) {
                // Server responded with error status
                const errorMessage = error.response.data.error || `Server error: ${error.response.status}`;
                this.showError(errorMessage);
            } else if (error.code === 'ECONNABORTED') {
                // Timeout
                this.showError('Bulk conversion timed out.');
            } else {
                // Network or other error
                this.showError('Network error. Please check your connection and try again.');
            }
        } finally {
            this.hideProgress();
            this.enableForm();
        }
    }

    async downloadFile() {
        if (!this.downloadUrl) {
            this.showToast('No file available for download.', 'error');
            return;
        }

        try {
            // Create a temporary link to trigger download
            const link = document.createElement('a');
            link.href = this.downloadUrl;
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showToast('Download started successfully!', 'success');
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed. Please try again.', 'error');
        }
    }

    showProgress() {
        document.getElementById('progressCard').classList.remove('d-none');
        document.getElementById('resultsCard').classList.add('d-none');
    }

    hideProgress() {
        document.getElementById('progressCard').classList.add('d-none');
    }

    showSuccess(originalFilename) {
        const resultsCard = document.getElementById('resultsCard');
        const successResult = document.getElementById('successResult');
        const errorResult = document.getElementById('errorResult');

        resultsCard.classList.remove('d-none');
        successResult.classList.remove('d-none');
        errorResult.classList.add('d-none');

        // Update success message with filename
        const cardText = successResult.querySelector('.card-text');
        cardText.textContent = `Your file "${originalFilename}" has been successfully processed.`;
    }

    showBulkSuccess(data) {
        const resultsCard = document.getElementById('resultsCard');
        const successResult = document.getElementById('successResult');
        const errorResult = document.getElementById('errorResult');

        resultsCard.classList.remove('d-none');
        successResult.classList.remove('d-none');
        errorResult.classList.add('d-none');

        // Update success message with bulk info
        const cardText = successResult.querySelector('.card-text');
        cardText.innerHTML = `
            <strong>Bulk conversion queued successfully!</strong><br>
            ${data.queued_files.length} files queued for conversion.<br>
            ${data.rejected_files.length} files rejected.<br><br>
            <small>Check the queue status below for conversion progress.</small>
        `;

        // Hide download button for bulk conversion
        document.getElementById('downloadBtn').style.display = 'none';
        
        // Show queue status card
        document.getElementById('queueStatusCard').classList.remove('d-none');
        document.getElementById('bulkModeCheckbox').checked = true;
    }

    showError(errorMessage) {
        const resultsCard = document.getElementById('resultsCard');
        const successResult = document.getElementById('successResult');
        const errorResult = document.getElementById('errorResult');
        const errorMessageElement = document.getElementById('errorMessage');

        resultsCard.classList.remove('d-none');
        successResult.classList.add('d-none');
        errorResult.classList.remove('d-none');
        errorMessageElement.textContent = errorMessage;
        
        // Show download button again
        document.getElementById('downloadBtn').style.display = 'inline-block';
    }

    resetForm() {
        // Hide results and progress
        document.getElementById('resultsCard').classList.add('d-none');
        document.getElementById('progressCard').classList.add('d-none');
        
        // Reset form
        document.getElementById('uploadForm').reset();
        
        // Clear state
        this.currentFileId = null;
        this.downloadUrl = null;
        
        // Enable form
        this.enableForm();
    }

    disableForm() {
        document.getElementById('convertBtn').disabled = true;
        document.getElementById('fileInput').disabled = true;
        document.getElementById('bulkModeCheckbox').disabled = true;
        document.getElementById('convertBtn').innerHTML = `
            <i class="fas fa-spinner fa-spin me-2"></i>
            Processing...
        `;
    }

    enableForm() {
        document.getElementById('convertBtn').disabled = false;
        document.getElementById('fileInput').disabled = false;
        document.getElementById('bulkModeCheckbox').disabled = false;
        document.getElementById('convertBtn').innerHTML = `
            <i class="fas fa-sync-alt me-2"></i>
            Convert to MP4
        `;
    }

    async checkApiStatus() {
        try {
            const response = await axios.get('/api/status');
            const data = response.data;
            
            const statusCard = document.getElementById('statusCard');
            const statusSpinner = document.getElementById('statusSpinner');
            const statusText = document.getElementById('statusText');

            statusSpinner.style.display = 'none';
            
            if (data.status === 'online' && data.ffmpeg_available) {
                statusCard.className = 'card mb-4 border-success';
                statusText.innerHTML = `
                    <i class="fas fa-check-circle text-success me-2"></i>
                    Service online and ready to convert files
                    <small class="text-muted d-block">
                        Max file size: ${data.max_file_size_mb}MB | 
                        Supported: ${data.supported_formats.join(', ').toUpperCase()} |
                        Queue: ${data.queue_size} files | Active: ${data.active_jobs} jobs
                    </small>
                `;
            } else {
                statusCard.className = 'card mb-4 border-warning';
                statusText.innerHTML = `
                    <i class="fas fa-exclamation-triangle text-warning me-2"></i>
                    Service issues detected - FFmpeg may not be available
                `;
            }
        } catch (error) {
            const statusCard = document.getElementById('statusCard');
            const statusSpinner = document.getElementById('statusSpinner');
            const statusText = document.getElementById('statusText');

            statusSpinner.style.display = 'none';
            statusCard.className = 'card mb-4 border-danger';
            statusText.innerHTML = `
                <i class="fas fa-times-circle text-danger me-2"></i>
                Service unavailable - Please try again later
            `;
            console.error('Error checking API status:', error);
        }
    }

    startQueuePolling() {
        // Clear any existing interval
        if (this.queueInterval) {
            clearInterval(this.queueInterval);
        }
        
        // Start polling queue status every 5 seconds
        this.queueInterval = setInterval(() => {
            this.updateQueueStatus();
        }, 5000);
    }

    async updateQueueStatus() {
        try {
            const response = await axios.get('/api/queue-status');
            const data = response.data;
            
            if (data.success) {
                this.renderQueueStatus(data.queue_status);
            }
        } catch (error) {
            console.error('Error updating queue status:', error);
        }
    }

    renderQueueStatus(queueStatus) {
        const queueItems = document.getElementById('queueItems');
        const queueCount = document.getElementById('queueCount');
        const queueEmptyMessage = document.getElementById('queueEmptyMessage');
        const queueCard = document.getElementById('queueStatusCard');
        
        // Update queue count
        const totalCount = Object.keys(queueStatus).length;
        queueCount.textContent = totalCount;
        
        // Show queue card if there are items or bulk mode is enabled
        const bulkMode = document.getElementById('bulkModeCheckbox').checked;
        if (totalCount > 0 || bulkMode) {
            queueCard.classList.remove('d-none');
        }
        
        if (totalCount === 0) {
            queueEmptyMessage.classList.remove('d-none');
            // Only clear items if there are no items to show
            if (queueItems.children.length > 0) {
                queueItems.innerHTML = '';
            }
            return;
        }
        
        queueEmptyMessage.classList.add('d-none');
        
        // Sort items by timestamp (oldest first)
        const sortedItems = Object.entries(queueStatus).sort((a, b) => 
            a[1].timestamp - b[1].timestamp
        );
        
        // Update or create queue items more efficiently
        this.updateQueueItems(sortedItems, queueItems);
    }

    updateQueueItems(sortedItems, queueItemsContainer) {
        // Create a map of existing items by file ID
        const existingItems = {};
        for (let i = 0; i < queueItemsContainer.children.length; i++) {
            const child = queueItemsContainer.children[i];
            const fileId = child.dataset.fileId;
            if (fileId) {
                existingItems[fileId] = child;
            }
        }
        
        // Update or create items
        const newItems = [];
        sortedItems.forEach(([fileId, status]) => {
            if (existingItems[fileId]) {
                // Update existing item
                this.updateQueueItem(existingItems[fileId], fileId, status);
                newItems.push(existingItems[fileId]);
                delete existingItems[fileId]; // Remove from existing items
            } else {
                // Create new item
                const newItem = this.createQueueItemElement(fileId, status);
                newItem.dataset.fileId = fileId; // Add file ID for future updates
                newItems.push(newItem);
            }
        });
        
        // Remove any remaining existing items (no longer in queue)
        Object.values(existingItems).forEach(item => item.remove());
        
        // Update the container with new order
        // Only update if the order has changed to prevent unnecessary reflows
        const currentOrder = Array.from(queueItemsContainer.children).map(child => child.dataset.fileId);
        const newOrder = newItems.map(item => item.dataset.fileId);
        
        if (JSON.stringify(currentOrder) !== JSON.stringify(newOrder)) {
            queueItemsContainer.innerHTML = '';
            newItems.forEach(item => queueItemsContainer.appendChild(item));
        }
    }
    
    updateQueueItem(itemElement, fileId, status) {
        // Update status badge
        let badgeClass = 'bg-secondary';
        let statusText = status.status;
        
        switch (status.status) {
            case 'queued':
                badgeClass = 'bg-info';
                break;
            case 'processing':
                badgeClass = 'bg-warning';
                break;
            case 'completed':
                badgeClass = 'bg-success';
                break;
            case 'error':
                badgeClass = 'bg-danger';
                break;
        }
        
        // Format filename (truncate if too long)
        const filename = status.filename || fileId;
        // Get the base filename without the extension and add .mp4
        const baseName = filename.substring(0, filename.lastIndexOf('.')) || filename;
        const mp4Filename = baseName + '.mp4';
        const displayFilename = mp4Filename.length > 30 
            ? mp4Filename.substring(0, 27) + '...' 
            : mp4Filename;
        
        // Update the content
        itemElement.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <strong title="${filename}">${displayFilename}</strong>
                    <br>
                    <small class="text-muted">${status.message}</small>
                </div>
                <div class="text-end">
                    <span class="badge ${badgeClass}">${statusText}</span>
                    <br>
                    ${status.status === 'completed' ? 
                        `<button class="btn btn-sm btn-success mt-1 download-btn" data-url="${status.download_url}">
                            <i class="fas fa-download"></i>
                        </button>` : 
                        ''}
                </div>
            </div>
        `;
        
        // Add event listener for download button
        const downloadBtn = itemElement.querySelector('.download-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => {
                this.downloadQueueFile(status.download_url);
            });
        }
    }

    createQueueItemElement(fileId, status) {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'border rounded p-3 mb-2';
        itemDiv.dataset.fileId = fileId; // Add file ID for future updates
        
        // Status badge
        let badgeClass = 'bg-secondary';
        let statusText = status.status;
        
        switch (status.status) {
            case 'queued':
                badgeClass = 'bg-info';
                break;
            case 'processing':
                badgeClass = 'bg-warning';
                break;
            case 'completed':
                badgeClass = 'bg-success';
                break;
            case 'error':
                badgeClass = 'bg-danger';
                break;
        }
        
        // Format filename (truncate if too long)
        const filename = status.filename || fileId;
        // Get the base filename without the extension and add .mp4
        const baseName = filename.substring(0, filename.lastIndexOf('.')) || filename;
        const mp4Filename = baseName + '.mp4';
        const displayFilename = mp4Filename.length > 30 
            ? mp4Filename.substring(0, 27) + '...' 
            : mp4Filename;
        
        itemDiv.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <strong title="${filename}">${displayFilename}</strong>
                    <br>
                    <small class="text-muted">${status.message}</small>
                </div>
                <div class="text-end">
                    <span class="badge ${badgeClass}">${statusText}</span>
                    <br>
                    ${status.status === 'completed' ? 
                        `<button class="btn btn-sm btn-success mt-1 download-btn" data-url="${status.download_url}">
                            <i class="fas fa-download"></i>
                        </button>` : 
                        ''}
                </div>
            </div>
        `;
        
        // Add event listener for download button
        const downloadBtn = itemDiv.querySelector('.download-btn');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => {
                this.downloadQueueFile(status.download_url);
            });
        }
        
        return itemDiv;
    }

    async downloadQueueFile(downloadUrl) {
        try {
            // Create a temporary link to trigger download
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showToast('Download started successfully!', 'success');
        } catch (error) {
            console.error('Download error:', error);
            this.showToast('Download failed. Please try again.', 'error');
        }
    }

    showToast(message, type = 'info') {
        const toastElement = document.getElementById('notificationToast');
        const toastMessage = document.getElementById('toastMessage');
        const toastHeader = toastElement.querySelector('.toast-header');
        const icon = toastHeader.querySelector('i');

        // Update toast content
        toastMessage.textContent = message;

        // Update icon and style based on type
        switch (type) {
            case 'success':
                icon.className = 'fas fa-check-circle me-2 text-success';
                break;
            case 'error':
                icon.className = 'fas fa-exclamation-triangle me-2 text-danger';
                break;
            case 'warning':
                icon.className = 'fas fa-exclamation-triangle me-2 text-warning';
                break;
            default:
                icon.className = 'fas fa-info-circle me-2 text-primary';
        }

        // Show toast
        const toast = new bootstrap.Toast(toastElement);
        toast.show();
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new VideoConverter();
});

// Add global error handler
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
});
