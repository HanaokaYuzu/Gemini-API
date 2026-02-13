package gemini

import (
	"bytes"
	"fmt"
	"io"
	"math/rand"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
)

func GenerateRandomName(extension string) string {
	return fmt.Sprintf("input_%d%s", rand.Intn(8999999)+1000000, extension)
}

func ParseFileName(file interface{}) (string, error) {
	switch v := file.(type) {
	case string:
		return filepath.Base(v), nil
	case []byte:
		return GenerateRandomName(".txt"), nil
	case io.Reader:
		return GenerateRandomName(".txt"), nil
	default:
		return "", fmt.Errorf("unsupported file type")
	}
}

func UploadFile(client *http.Client, file interface{}, filename string) (string, error) {
	var fileContent []byte
	var err error

	switch v := file.(type) {
	case string:
		if filename == "" {
			filename = filepath.Base(v)
		}
		fileContent, err = os.ReadFile(v)
		if err != nil {
			return "", err
		}
	case []byte:
		fileContent = v
		if filename == "" {
			filename = GenerateRandomName(".txt")
		}
	case io.Reader:
		fileContent, err = io.ReadAll(v)
		if err != nil {
			return "", err
		}
		if filename == "" {
			filename = GenerateRandomName(".txt")
		}
	default:
		return "", fmt.Errorf("unsupported file type: %T", file)
	}

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("file", filename)
	if err != nil {
		return "", err
	}
	_, err = part.Write(fileContent)
	if err != nil {
		return "", err
	}
	err = writer.Close()
	if err != nil {
		return "", err
	}

	req, err := http.NewRequest("POST", EndpointUpload, body)
	if err != nil {
		return "", err
	}

	req.Header.Set("Content-Type", writer.FormDataContentType())
	for k, v := range HeadersUpload {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", fmt.Errorf("upload failed with status: %s", resp.Status)
	}

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	return string(respBody), nil
}
