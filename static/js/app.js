class VideoConverter {
    constructor() {
        this.currentFileId = null;
        this.downloadUrl = null;
        this.initializeEventListeners();
        this.checkApiStatus();
    }

    initializeEventListeners() {
        // Form submission
        document.getElementById('uploadForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFileUpload();
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
            this.validateFileInput(e.target);
        });
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
                        Supported: ${data.supported_formats.join(', ').toUpperCase()}
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

    validateFileInput(input) {
        const file = input.files[0];
        if (!file) return;

        // Check file size (500MB limit)
        const maxSize = 500 * 1024 * 1024; // 500MB in bytes
        if (file.size > maxSize) {
            this.showToast('File too large. Maximum size is 500MB.', 'error');
            input.value = '';
            return false;
        }

        // Check file type
        if (!file.type.includes('webm') && !file.name.toLowerCase().endsWith('.webm')) {
            this.showToast('Please select a valid WebM file.', 'error');
            input.value = '';
            return false;
        }

        return true;
    }

    async handleFileUpload() {
        const fileInput = document.getElementById('fileInput');
        const file = fileInput.files[0];

        if (!file) {
            this.showToast('Please select a file first.', 'error');
            return;
        }

        if (!this.validateFileInput(fileInput)) {
            return;
        }

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
        cardText.textContent = `Your WebM file "${originalFilename}" has been successfully converted to MP4.`;
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
        document.getElementById('convertBtn').innerHTML = `
            <i class="fas fa-spinner fa-spin me-2"></i>
            Converting...
        `;
    }

    enableForm() {
        document.getElementById('convertBtn').disabled = false;
        document.getElementById('fileInput').disabled = false;
        document.getElementById('convertBtn').innerHTML = `
            <i class="fas fa-sync-alt me-2"></i>
            Convert to MP4
        `;
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
